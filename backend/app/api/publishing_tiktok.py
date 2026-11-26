"""Connecting and disconnecting a TikTok account, and what its creator may choose.

- ``GET /publishing/tiktok`` — whether this server offers TikTok and the user's connection.
- ``POST /publishing/tiktok/connect`` — a fresh single-use state, then TikTok's consent URL for
  the browser to open (a POST, so another site cannot start it).
- ``GET /publishing/tiktok/callback`` — TikTok redirects here. The state must be the one this
  signed-in user started; the code is exchanged server-side and the refresh token stored
  encrypted. The browser always goes back to the fixed ``/settings`` page with an allow-listed
  outcome — never to a URL from the request, never with a token.
- ``GET /publishing/tiktok/creator`` — the account's name and the visibility levels and
  interaction switches TikTok offers it right now (the publish dialog shows exactly these).
- ``DELETE /publishing/tiktok`` — revoke with TikTok (best effort) and delete the token.
"""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession, get_current_user
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import ConnectionStatus, PublishingProvider
from app.schemas.publishing import (
    AuthorizationRead,
    DisconnectRead,
    PublishingConnectionRead,
    TikTokCreatorRead,
    TikTokStatusRead,
)
from app.services.publishing import connections, tiktok_post
from app.services.publishing import tiktok_oauth as oauth
from app.services.publishing.provider import (
    ProviderAuth,
    PublishErrorCode,
    PublishProviderError,
)
from app.services.publishing.tokens import TokenCipher, TokenDecryptionError, TokenKeyError
from app.services.publishing.youtube_oauth import OAuthError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/publishing/tiktok", tags=["publishing"])
SETTINGS_PATH = "/settings"
TIKTOK = PublishingProvider.TIKTOK


def _require_enabled() -> None:
    if not get_settings().tiktok_publishing_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TikTok publishing is not enabled on this server",
        )


@router.get("", response_model=TikTokStatusRead)
def tiktok_status(current_user: CurrentUser, db: DbSession) -> TikTokStatusRead:
    connection = connections.get_connection(db, current_user.id, TIKTOK)
    return TikTokStatusRead(
        enabled=get_settings().tiktok_publishing_enabled,
        connection=PublishingConnectionRead.model_validate(connection) if connection else None,
    )


@router.post("/connect", response_model=AuthorizationRead, dependencies=[per_user("oauth_start")])
def connect_tiktok(current_user: CurrentUser, db: DbSession) -> AuthorizationRead:
    _require_enabled()
    settings = get_settings()
    url = oauth.start(db, settings, TokenCipher.from_settings(settings), current_user.id)
    return AuthorizationRead(authorization_url=url)


def _back_to_settings(outcome: str, reason: str | None = None) -> RedirectResponse:
    query = {"tiktok": outcome, **({"reason": reason} if reason else {})}
    target = f"{get_settings().frontend_url.rstrip('/')}{SETTINGS_PATH}?{urlencode(query)}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"  # the code must not leak onward
    return response


def _account_name(access_token: str) -> str:
    """The account's @name, asked once with the token that came with the grant. Display only:
    a problem here never stops the connection."""
    from app.services.publishing.factory import get_publishing_provider

    try:
        provider = get_publishing_provider(get_settings(), TIKTOK.value)
        info = provider.creator_info(ProviderAuth(access_token))
    except Exception:  # noqa: BLE001 — the name is optional
        return ""
    return f"@{info.username}" if info.username else info.nickname


@router.get("/callback", include_in_schema=False)
def tiktok_callback(
    request: Request,
    db: DbSession,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    settings = get_settings()
    if not settings.tiktok_publishing_enabled:
        return _back_to_settings("error", "disabled")
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _back_to_settings("error", "signin_required")
    try:
        oauth.consume_state(db, state, user.id)
        if error:  # the user declined (or TikTok refused) on the consent screen
            raise OAuthError("denied")
        grant = oauth.exchange_code(settings, code)
    except OAuthError as failure:
        logger.info("TikTok authorization not completed: %s", failure.code)
        return _back_to_settings("error", failure.code)
    connections.save_connection(
        db, TokenCipher.from_settings(settings), user_id=user.id,
        refresh_token=grant.refresh_token, account_id=grant.open_id,
        account_title=_account_name(grant.access_token) if grant.access_token else "",
        scopes=grant.scopes, provider=TIKTOK,
    )  # fmt: skip
    logger.info("TikTok authorization completed")
    return _back_to_settings("connected")


@router.get("/creator", response_model=TikTokCreatorRead, dependencies=[per_user("tiktok_creator")])
def tiktok_creator(current_user: CurrentUser, db: DbSession) -> TikTokCreatorRead:
    """What TikTok lets this creator choose for a post, asked from TikTok now."""
    _require_enabled()
    connection = connections.get_connection(db, current_user.id, TIKTOK)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No TikTok connection")
    if connection.status != ConnectionStatus.CONNECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Reconnect your TikTok account"
        )
    try:
        info = tiktok_post.creator_info(db, get_settings(), connection)
    except (TokenKeyError, TokenDecryptionError):
        connections.mark_needs_reconnect(db, connection)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Reconnect your TikTok account"
        ) from None
    except PublishProviderError as failure:
        if failure.code == PublishErrorCode.AUTHENTICATION_REQUIRED:
            connections.mark_needs_reconnect(db, connection)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Reconnect your TikTok account"
            ) from None
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=failure.message
        ) from None
    if info.username and not connection.account_title:
        connection.account_title = f"@{info.username}"[:255]
        db.commit()
    return TikTokCreatorRead(
        nickname=info.nickname,
        username=info.username,
        privacy_levels=list(info.privacy_levels),
        comment_disabled=info.comment_disabled,
        duet_disabled=info.duet_disabled,
        stitch_disabled=info.stitch_disabled,
        max_duration_seconds=info.max_duration_seconds,
    )


@router.delete("", response_model=DisconnectRead)
def disconnect_tiktok(current_user: CurrentUser, db: DbSession) -> DisconnectRead:
    connection = connections.get_connection(db, current_user.id, TIKTOK)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No TikTok connection")
    settings = get_settings()
    cipher = (
        TokenCipher.from_settings(settings)
        if settings.publishing_token_encryption_key is not None
        else None
    )
    revoked = connections.disconnect(
        db, cipher, connection, lambda token: oauth.revoke(settings, token)
    )
    return DisconnectRead(revoked_with_provider=revoked)
