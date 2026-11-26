"""Instagram authorization through Facebook Login for Business (Graph API v27.0).

Why this path: it is the one Meta documents for uploading a Reel's bytes from the server
(``rupload.facebook.com``). Instagram Login only lets Meta fetch a public URL, and PeakSift's
media is never public. It needs an Instagram professional account linked to a Facebook Page.

The same rules as the other platforms: a single-use, user-bound, hashed, short-lived ``state``
that no other platform's callback can consume; the code is exchanged server-side with the app
secret; one secret is kept, encrypted. Meta has no refresh token: the short-lived user token is
traded for a long-lived one, which lists the creator's Pages, and the **Page access token** of
the first Page with an Instagram professional account is kept (Meta documents long-lived Page
tokens as not expiring). It is stored with that account's id, as one sealed value.

Meta's messages, tokens and codes never leave this module.
"""

import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import OAuthState, PublishingProvider
from app.services.publishing.tokens import TokenCipher
from app.services.publishing.youtube_oauth import OAuthError

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v27.0"
DIALOG_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
TOKEN_URL = f"{GRAPH}/oauth/access_token"
PUBLISH_PERMISSION = "instagram_content_publish"
PERMISSIONS = ("instagram_basic", PUBLISH_PERMISSION, "pages_show_list", "pages_read_engagement")
STATE_TTL = timedelta(minutes=10)
PROVIDER = PublishingProvider.INSTAGRAM.value
_STATE_PURPOSE = "instagram-state"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass(frozen=True)
class Grant:
    # The sealed value the connection keeps: the Page token and the Instagram account's id.
    refresh_token: str = field(repr=False)
    scopes: list[str]
    account_id: str  # the Instagram professional account's id
    username: str  # its @name, for display


def seal(page_token: str, account_id: str) -> str:
    return json.dumps({"t": page_token, "ig": account_id}, separators=(",", ":"))


def unseal(stored: str) -> tuple[str, str] | None:
    """``(page_token, account_id)`` from a stored value, or None when it is not one."""
    try:
        data = json.loads(stored)
        token, account = data["t"], data["ig"]
    except (ValueError, KeyError, TypeError):
        return None
    if isinstance(token, str) and token and isinstance(account, str) and account.isdigit():
        return token, account
    return None


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def start(db: Session, settings: Settings, cipher: TokenCipher, user_id: uuid.UUID) -> str:
    """Record a fresh single-use state for ``user_id`` and return Meta's consent URL."""
    state = secrets.token_urlsafe(32)
    sealed = cipher.encrypt(secrets.token_urlsafe(16), user_id=user_id, provider=_STATE_PURPOSE)
    now = datetime.now(UTC)
    db.execute(delete(OAuthState).where(OAuthState.user_id == user_id))
    db.execute(delete(OAuthState).where(OAuthState.expires_at < now))
    db.add(
        OAuthState(
            user_id=user_id, provider=PROVIDER, purpose="publishing", state_hash=_hash(state),
            code_verifier_ciphertext=sealed.ciphertext, key_version=sealed.key_version,
            expires_at=now + STATE_TTL,
        )
    )  # fmt: skip
    db.commit()
    query = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.instagram_oauth_redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": ",".join(PERMISSIONS),
    }
    return f"{DIALOG_URL}?{urlencode(query)}"


def consume_state(db: Session, state: str, user_id: uuid.UUID) -> None:
    """Delete the state (single use, atomically) or raise :class:`OAuthError`."""
    if not state or len(state) > 256:
        raise OAuthError("invalid_state")
    row = db.execute(
        delete(OAuthState)
        .where(OAuthState.state_hash == _hash(state), OAuthState.provider == PROVIDER)
        .returning(OAuthState.user_id, OAuthState.expires_at)
    ).first()
    db.commit()
    if row is None or row.user_id != user_id:
        raise OAuthError("invalid_state")
    if row.expires_at < datetime.now(UTC):
        raise OAuthError("expired")


def _get(client: httpx.Client, url: str, *, params: dict, token: str | None = None) -> dict:
    headers = {"Authorization": f"OAuth {token}"} if token else {}
    try:
        response = client.get(url, params=params, headers=headers)
        body = response.json()
    except (httpx.HTTPError, ValueError):
        raise OAuthError("exchange_failed") from None
    if response.status_code >= 400 or not isinstance(body, dict) or "error" in body:
        logger.info("Meta refused an authorization request (%s)", response.status_code)
        raise OAuthError("exchange_failed")
    return body


def exchange_code(settings: Settings, code: str, client: httpx.Client | None = None) -> Grant:
    """Code → user token → long-lived user token → the Page token of the creator's Instagram
    professional account. Publishing must have been granted."""
    if not code:
        raise OAuthError("denied")
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    secret = settings.meta_app_secret.get_secret_value()
    try:
        short = _get(client, TOKEN_URL, params={
            "client_id": settings.meta_app_id, "client_secret": secret,
            "redirect_uri": settings.instagram_oauth_redirect_uri, "code": code,
        }).get("access_token")  # fmt: skip
        if not isinstance(short, str) or not short:
            raise OAuthError("exchange_failed")
        long_lived = _get(client, TOKEN_URL, params={
            "grant_type": "fb_exchange_token", "client_id": settings.meta_app_id,
            "client_secret": secret, "fb_exchange_token": short,
        }).get("access_token")  # fmt: skip
        if not isinstance(long_lived, str) or not long_lived:
            raise OAuthError("missing_refresh_token")
        granted = [
            str(item.get("permission"))
            for item in _get(client, f"{GRAPH}/me/permissions", params={}, token=long_lived).get(
                "data", []
            )
            if isinstance(item, dict) and item.get("status") == "granted"
        ]
        if PUBLISH_PERMISSION not in granted:
            raise OAuthError("insufficient_scope")
        pages = _get(
            client,
            f"{GRAPH}/me/accounts",
            params={"fields": "id,name,access_token,instagram_business_account{id,username}"},
            token=long_lived,
        ).get("data", [])
    finally:
        if owned:
            client.close()
    for page in pages if isinstance(pages, list) else []:
        account = page.get("instagram_business_account") if isinstance(page, dict) else None
        token = page.get("access_token") if isinstance(page, dict) else None
        if isinstance(account, dict) and str(account.get("id", "")).isdigit() and token:
            return Grant(
                seal(str(token), str(account["id"])),
                granted,
                str(account["id"])[:128],
                str(account.get("username") or "")[:200],
            )
    raise OAuthError("no_instagram_account")


def revoke(token: str) -> None:
    """Meta's documented way to remove an app's permissions needs the user's own token, which
    PeakSift does not keep. Disconnecting therefore deletes the Page token here only, and the
    creator is told to remove PeakSift in their Facebook settings too."""
    raise OAuthError("exchange_failed")
