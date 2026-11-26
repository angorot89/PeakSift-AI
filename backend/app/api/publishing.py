"""Connecting and disconnecting a YouTube account, and the list of platforms.

- ``GET /publishing/platforms`` — every platform PeakSift can publish to, whether this server
  offers it, and the creator's connection to each.

- ``GET /publishing/youtube`` — whether publishing is enabled and the user's connection.
- ``POST /publishing/youtube/connect`` — start: a fresh single-use state, then Google's
  consent URL for the browser to open (a POST, so another site cannot start it).
- ``POST /publishing/youtube/analytics/connect`` — the explicit analytics upgrade (V1.4): the
  same, asking for upload plus the two read-only analytics scopes. Never started implicitly.
- ``GET /publishing/youtube/callback`` — Google redirects here. The state must be the one
  this signed-in user started; the code is exchanged server-side and the refresh token
  stored encrypted. The browser is always sent to the fixed ``/settings`` page with an
  allow-listed outcome — never to a URL from the request, and never with a token.
  An analytics callback saves the new token only when upload *and* both read scopes were
  granted; otherwise the existing connection is left exactly as it was.
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
    PlatformRead,
    PublishingConnectionRead,
    YouTubeStatusRead,
)
from app.services.performance.lifecycle import start_backfill_quietly
from app.services.publishing import connections, platforms
from app.services.publishing import youtube_oauth as oauth
from app.services.publishing.tokens import TokenCipher, TokenDecryptionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publishing/youtube", tags=["publishing"])
platforms_router = APIRouter(prefix="/publishing/platforms", tags=["publishing"])

SETTINGS_PATH = "/settings"


def _cipher(settings: Settings) -> TokenCipher | None:
    if settings.publishing_token_encryption_key is None:
        return None
    return TokenCipher.from_settings(settings)


@router.get("", response_model=YouTubeStatusRead)
def youtube_status(current_user: CurrentUser, db: DbSession) -> YouTubeStatusRead:
    connection = connections.get_connection(db, current_user.id)
    settings = get_settings()
    return YouTubeStatusRead(
        enabled=settings.youtube_publishing_enabled,
        analytics_enabled=settings.youtube_publishing_enabled
        and settings.youtube_analytics_enabled,
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


@router.post(
    "/analytics/connect",
    response_model=AuthorizationRead,
    dependencies=[per_user("oauth_start")],
)
def connect_youtube_analytics(current_user: CurrentUser, db: DbSession) -> AuthorizationRead:
    settings = get_settings()
    if not (settings.youtube_publishing_enabled and settings.youtube_analytics_enabled):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="YouTube analytics is not enabled on this server",
        )
    cipher = TokenCipher.from_settings(settings)
    url = oauth.start(db, settings, cipher, current_user.id, purpose="analytics")
    return AuthorizationRead(authorization_url=url)


def _back_to_settings(
    outcome: str, reason: str | None = None, *, key: str = "youtube"
) -> RedirectResponse:
    query = {key: outcome, **({"reason": reason} if reason else {})}
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
    key = "youtube"
    try:
        pending = oauth.consume_state(db, cipher, state, user.id)
        if pending.purpose == "analytics":
            key = "analytics"
            if not settings.youtube_analytics_enabled:
                raise oauth.OAuthError("disabled")
        if error:  # the user declined (or Google refused) on the consent screen
            raise oauth.OAuthError("denied")
        grant = oauth.exchange_code(settings, code, pending.code_verifier, pending.purpose)
    except oauth.OAuthError as failure:
        logger.info("YouTube %s authorization not completed: %s", key, failure.code)
        return _back_to_settings("error", failure.code, key=key)
    except TokenDecryptionError:
        return _back_to_settings("error", "invalid_state", key=key)
    existing = connections.get_connection(db, user.id)
    connections.save_connection(
        db, cipher, user_id=user.id, refresh_token=grant.refresh_token,
        account_id=existing.account_id if existing and key == "analytics" else "",
        account_title=existing.account_title if existing and key == "analytics" else "",
        scopes=grant.scopes,
    )  # fmt: skip
    logger.info("YouTube %s authorization completed", key)
    if key == "analytics":  # sync PeakSift's own uploads (only those) from now on
        start_backfill_quietly(db, user.id, settings)
    return _back_to_settings("connected", key=key)


@router.delete("", response_model=DisconnectRead)
def disconnect_youtube(current_user: CurrentUser, db: DbSession) -> DisconnectRead:
    connection = connections.get_connection(db, current_user.id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No YouTube connection")
    revoked = connections.disconnect(db, _cipher(get_settings()), connection, oauth.revoke)
    return DisconnectRead(revoked_with_provider=revoked)


@platforms_router.get("", response_model=list[PlatformRead])
def list_platforms(current_user: CurrentUser, db: DbSession) -> list[PlatformRead]:
    """Every platform PeakSift can publish to, whether this server offers it, and the
    creator's own connection to each. Never tokens or scopes."""
    settings = get_settings()
    connected = connections.list_connections(db, current_user.id)
    return [
        PlatformRead(
            key=platform.key,
            label=platform.label,
            account_noun=platform.account_noun,
            enabled=platform.enabled(settings),
            connection=PublishingConnectionRead.model_validate(connected[platform.key])
            if platform.key in connected
            else None,
        )
        for platform in platforms.PLATFORMS
    ]
