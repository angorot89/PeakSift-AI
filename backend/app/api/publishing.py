"""Connecting and disconnecting a YouTube account.

- ``GET /publishing/youtube`` — whether publishing is enabled and the user's connection.
- ``POST /publishing/youtube/connect`` — start: a fresh single-use state, then Google's
  consent URL for the browser to open (a POST, so another site cannot start it).
- ``GET /publishing/youtube/callback`` — Google redirects here. The state must be the one
  this signed-in user started; the code is exchanged server-side and the refresh token
  stored encrypted. The browser is always sent to the fixed ``/settings`` page with an
  allow-listed outcome — never to a URL from the request, and never with a token.
- ``DELETE /publishing/youtube`` — revoke with Google (best effort) and delete the token.
"""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession, get_current_user
from app.core.config import Settings, get_settings
from app.core.rate_limit import per_user
from app.schemas.publishing import (
    AuthorizationRead,
    DisconnectRead,
    PublishingConnectionRead,
    YouTubeStatusRead,
)
from app.services.publishing import connections
from app.services.publishing import youtube_oauth as oauth
from app.services.publishing.tokens import TokenCipher, TokenDecryptionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publishing/youtube", tags=["publishing"])

SETTINGS_PATH = "/settings"


def _cipher(settings: Settings) -> TokenCipher | None:
    if settings.publishing_token_encryption_key is None:
        return None
    return TokenCipher.from_settings(settings)


@router.get("", response_model=YouTubeStatusRead)
def youtube_status(current_user: CurrentUser, db: DbSession) -> YouTubeStatusRead:
    connection = connections.get_connection(db, current_user.id)
    return YouTubeStatusRead(
        enabled=get_settings().youtube_publishing_enabled,
        connection=PublishingConnectionRead.model_validate(connection) if connection else None,
    )


@router.post("/connect", response_model=AuthorizationRead, dependencies=[per_user("oauth_start")])
def connect_youtube(current_user: CurrentUser, db: DbSession) -> AuthorizationRead:
    settings = get_settings()
    if not settings.youtube_publishing_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="YouTube publishing is not enabled on this server",
        )
    url = oauth.start(db, settings, TokenCipher.from_settings(settings), current_user.id)
    return AuthorizationRead(authorization_url=url)


def _back_to_settings(outcome: str, reason: str | None = None) -> RedirectResponse:
    query = {"youtube": outcome, **({"reason": reason} if reason else {})}
    target = f"{get_settings().frontend_url.rstrip('/')}{SETTINGS_PATH}?{urlencode(query)}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"  # the code must not leak onward
    return response


@router.get("/callback", include_in_schema=False)
def youtube_callback(
    request: Request,
    db: DbSession,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    settings = get_settings()
    if not settings.youtube_publishing_enabled:
        return _back_to_settings("error", "disabled")
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _back_to_settings("error", "signin_required")
    cipher = TokenCipher.from_settings(settings)
    try:
        verifier = oauth.consume_state(db, cipher, state, user.id)
        if error:  # the user declined (or Google refused) on the consent screen
            raise oauth.OAuthError("denied")
        grant = oauth.exchange_code(settings, code, verifier)
    except oauth.OAuthError as failure:
        logger.info("YouTube connection not completed: %s", failure.code)
        return _back_to_settings("error", failure.code)
    except TokenDecryptionError:
        return _back_to_settings("error", "invalid_state")
    connections.save_connection(
        db, cipher, user_id=user.id, refresh_token=grant.refresh_token, account_id="",
        account_title="", scopes=grant.scopes,
    )  # fmt: skip
    logger.info("YouTube account connected")
    return _back_to_settings("connected")


@router.delete("", response_model=DisconnectRead)
def disconnect_youtube(current_user: CurrentUser, db: DbSession) -> DisconnectRead:
    connection = connections.get_connection(db, current_user.id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No YouTube connection")
    revoked = connections.disconnect(db, _cipher(get_settings()), connection, oauth.revoke)
    return DisconnectRead(revoked_with_provider=revoked)
