"""Connecting a YouTube account with Google's official OAuth libraries.

- **Scope:** ``youtube.upload`` only — enough to upload a video, nothing else (it cannot
  read, edit or delete the user's videos). No OpenID scopes are requested, so the
  connection shows the channel's name only once the first upload reports it.
- **Flow:** server-side authorization code with PKCE (S256) and ``access_type=offline`` +
  ``prompt=consent`` so Google returns a refresh token. The ``state`` is random, single-use,
  bound to the user who started and valid for ten minutes (``OAuthState``).
- **Secrets:** the client secret comes from configuration; codes, verifiers and tokens never
  reach the browser, the logs or an error message. Google SDK objects never leave this
  module; failures become an :class:`OAuthError` with an allow-listed code.
"""

import hashlib
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import OAuthState, PublishingProvider
from app.services.publishing.tokens import EncryptedToken, TokenCipher

logger = logging.getLogger(__name__)

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
STATE_TTL = timedelta(minutes=10)
PROVIDER = PublishingProvider.YOUTUBE.value
_VERIFIER_PURPOSE = "youtube-pkce"

# Codes the callback may report to the frontend (nothing else ever reaches the URL).
ERROR_CODES = frozenset(
    {"denied", "invalid_state", "expired", "signin_required", "missing_refresh_token",
     "insufficient_scope", "exchange_failed", "disabled"}
)  # fmt: skip


class OAuthError(Exception):
    def __init__(self, code: str) -> None:
        assert code in ERROR_CODES
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Grant:
    refresh_token: str
    scopes: list[str]


def _client_config(settings: Settings) -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.google_oauth_redirect_uri],
        }
    }


def _flow(settings: Settings, *, code_verifier: str | None = None):
    from google_auth_oauthlib.flow import Flow

    # Google may report scopes in another order or form; our own check below decides.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    return Flow.from_client_config(
        _client_config(settings),
        scopes=[UPLOAD_SCOPE],
        redirect_uri=settings.google_oauth_redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def start(db: Session, settings: Settings, cipher: TokenCipher, user_id: uuid.UUID) -> str:
    """Record a fresh single-use state for ``user_id`` and return Google's consent URL."""
    state = secrets.token_urlsafe(32)
    flow = _flow(settings)
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="false",
        state=state,
    )
    sealed = cipher.encrypt(flow.code_verifier, user_id=user_id, provider=_VERIFIER_PURPOSE)
    now = datetime.now(UTC)
    # One connection attempt at a time per user; expired states are cleared as we go.
    db.execute(delete(OAuthState).where(OAuthState.user_id == user_id))
    db.execute(delete(OAuthState).where(OAuthState.expires_at < now))
    db.add(
        OAuthState(
            user_id=user_id, provider=PROVIDER, state_hash=_hash(state),
            code_verifier_ciphertext=sealed.ciphertext, key_version=sealed.key_version,
            expires_at=now + STATE_TTL,
        )
    )  # fmt: skip
    db.commit()
    return url


def consume_state(db: Session, cipher: TokenCipher, state: str, user_id: uuid.UUID) -> str:
    """Delete the state (single use, atomically) and return its PKCE verifier."""
    if not state or len(state) > 256:
        raise OAuthError("invalid_state")
    row = db.execute(
        delete(OAuthState)
        .where(OAuthState.state_hash == _hash(state))
        .returning(
            OAuthState.user_id,
            OAuthState.expires_at,
            OAuthState.code_verifier_ciphertext,
            OAuthState.key_version,
        )
    ).first()
    db.commit()
    if row is None or row.user_id != user_id:
        raise OAuthError("invalid_state")
    if row.expires_at < datetime.now(UTC):
        raise OAuthError("expired")
    return cipher.decrypt(
        EncryptedToken(row.code_verifier_ciphertext, row.key_version),
        user_id=user_id,
        provider=_VERIFIER_PURPOSE,
    )


def _fetch_token(flow, code: str) -> None:
    """The network exchange (isolated so tests replace it; never logs the code)."""
    flow.fetch_token(code=code)


def exchange_code(settings: Settings, code: str, code_verifier: str) -> Grant:
    """Trade the authorization code for a refresh token; check what was granted."""
    if not code or len(code) > 2048:
        raise OAuthError("exchange_failed")
    flow = _flow(settings, code_verifier=code_verifier)
    try:
        _fetch_token(flow, code)
    except Exception as error:  # noqa: BLE001 — any failure of the exchange
        logger.warning("YouTube authorization exchange failed: %s", type(error).__name__)
        raise OAuthError("exchange_failed") from None
    credentials = flow.credentials
    granted = list(getattr(credentials, "granted_scopes", None) or credentials.scopes or [])
    if UPLOAD_SCOPE not in granted:
        raise OAuthError("insufficient_scope")
    if not credentials.refresh_token:
        raise OAuthError("missing_refresh_token")
    return Grant(credentials.refresh_token, granted)


def revoke(token: str) -> None:
    """Ask Google to revoke the token (raises on failure; callers treat it as best effort)."""
    import httpx

    response = httpx.post(REVOKE_URI, data={"token": token}, timeout=10)
    if response.status_code != 200:
        raise RuntimeError(f"revocation answered {response.status_code}")
