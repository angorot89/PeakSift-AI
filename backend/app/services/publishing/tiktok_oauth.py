"""TikTok authorization (Login Kit for Web, OAuth v2) for publishing.

The same rules as YouTube's: a single-use, user-bound, hashed, short-lived ``state``; the code
is exchanged server-side with the client secret; only the refresh token is kept, encrypted;
the one scope asked for is ``video.publish``. Two things differ and matter:

- TikTok's web flow has no PKCE, so the state row's verifier slot holds a random value that is
  never used (the column is shared with YouTube's flow).
- **Refresh tokens rotate**: every refresh answers with a new refresh token and the old one
  stops working (see ``tiktok.py`` and ``ProviderAuth.rotated_refresh_token``).

TikTok's messages, tokens and codes never leave this module; failures are an
:class:`OAuthError` with one of the allow-listed codes the Settings page can show.
"""

import hashlib
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

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
PUBLISH_SCOPE = "video.publish"
STATE_TTL = timedelta(minutes=10)
PROVIDER = PublishingProvider.TIKTOK.value
_STATE_PURPOSE = "tiktok-state"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass(frozen=True)
class Grant:
    refresh_token: str = field(repr=False)
    scopes: list[str]
    open_id: str  # TikTok's id for this user in this app: display and bookkeeping only
    # The access token issued with the grant: used once, to learn the account's name. Never
    # stored.
    access_token: str = field(default="", repr=False)


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def start(db: Session, settings: Settings, cipher: TokenCipher, user_id: uuid.UUID) -> str:
    """Record a fresh single-use state for ``user_id`` and return TikTok's consent URL."""
    state = secrets.token_urlsafe(32)
    sealed = cipher.encrypt(secrets.token_urlsafe(16), user_id=user_id, provider=_STATE_PURPOSE)
    now = datetime.now(UTC)
    # One connection attempt at a time per user; expired states are cleared as we go.
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
        "client_key": settings.tiktok_client_key,
        "scope": PUBLISH_SCOPE,
        "response_type": "code",
        "redirect_uri": settings.tiktok_oauth_redirect_uri,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(query)}"


def consume_state(db: Session, state: str, user_id: uuid.UUID) -> None:
    """Delete the state (single use, atomically) or raise :class:`OAuthError`. Only a state
    this user started for TikTok passes."""
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


def _post(url: str, form: dict[str, str], client: httpx.Client | None) -> httpx.Response:
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        return client.post(url, data=form, headers={"Cache-Control": "no-cache"})
    except httpx.HTTPError:
        raise OAuthError("exchange_failed") from None
    finally:
        if owned:
            client.close()


def exchange_code(settings: Settings, code: str, client: httpx.Client | None = None) -> Grant:
    """Trade the authorization code for tokens. The publish scope must have been granted."""
    if not code:
        raise OAuthError("denied")
    response = _post(
        TOKEN_URL,
        {
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret.get_secret_value(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.tiktok_oauth_redirect_uri,
        },
        client,
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code >= 400 or not isinstance(body, dict) or body.get("error"):
        logger.info("TikTok code exchange was refused (%s)", response.status_code)
        raise OAuthError("exchange_failed")
    refresh_token = body.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise OAuthError("missing_refresh_token")
    scopes = [s for s in str(body.get("scope") or "").replace(" ", ",").split(",") if s]
    if PUBLISH_SCOPE not in scopes:
        raise OAuthError("insufficient_scope")
    return Grant(
        refresh_token,
        scopes,
        str(body.get("open_id") or "")[:128],
        str(body.get("access_token") or ""),
    )


def revoke(settings: Settings, token: str, client: httpx.Client | None = None) -> None:
    """Ask TikTok to revoke the grant. Raises when TikTok did not confirm it."""
    response = _post(
        REVOKE_URL,
        {
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret.get_secret_value(),
            "token": token,
        },
        client,
    )
    if response.status_code >= 400:
        raise OAuthError("exchange_failed")
