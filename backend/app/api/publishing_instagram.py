"""Connecting and disconnecting an Instagram professional account (Facebook Login).

- ``GET /publishing/instagram`` — whether this server offers Instagram and the connection.
- ``POST /publishing/instagram/connect`` — a fresh single-use state, then Meta's consent URL
  for the browser to open (a POST, so another site cannot start it).
- ``GET /publishing/instagram/callback`` — Meta redirects here. The state must be the one this
  signed-in user started; the code is exchanged server-side and the Page token stored
  encrypted. The browser always goes back to the fixed ``/settings`` page with an allow-listed
  outcome — never to a URL from the request, never with a token.
- ``DELETE /publishing/instagram`` — delete the stored Page token. Meta's removal needs the
  creator's own user token, which PeakSift does not keep, so the creator is told to remove
  PeakSift in their Facebook settings too.
"""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession, get_current_user
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import PublishingProvider
from app.schemas.publishing import (
    AuthorizationRead,
    DisconnectRead,
    InstagramStatusRead,
    PublishingConnectionRead,
)
from app.services.publishing import connections
from app.services.publishing import instagram_oauth as oauth
from app.services.publishing.tokens import TokenCipher
from app.services.publishing.youtube_oauth import OAuthError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/publishing/instagram", tags=["publishing"])
SETTINGS_PATH = "/settings"
INSTAGRAM = PublishingProvider.INSTAGRAM


@router.get("", response_model=InstagramStatusRead)
def instagram_status(current_user: CurrentUser, db: DbSession) -> InstagramStatusRead:
    connection = connections.get_connection(db, current_user.id, INSTAGRAM)
    return InstagramStatusRead(
        enabled=get_settings().instagram_publishing_enabled,
        connection=PublishingConnectionRead.model_validate(connection) if connection else None,
    )


@router.post("/connect", response_model=AuthorizationRead, dependencies=[per_user("oauth_start")])
def connect_instagram(current_user: CurrentUser, db: DbSession) -> AuthorizationRead:
    settings = get_settings()
    if not settings.instagram_publishing_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instagram publishing is not enabled on this server",
        )
    url = oauth.start(db, settings, TokenCipher.from_settings(settings), current_user.id)
    return AuthorizationRead(authorization_url=url)


def _back_to_settings(outcome: str, reason: str | None = None) -> RedirectResponse:
    query = {"instagram": outcome, **({"reason": reason} if reason else {})}
    target = f"{get_settings().frontend_url.rstrip('/')}{SETTINGS_PATH}?{urlencode(query)}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"  # the code must not leak onward
    return response


@router.get("/callback", include_in_schema=False)
def instagram_callback(
    request: Request,
    db: DbSession,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    settings = get_settings()
    if not settings.instagram_publishing_enabled:
        return _back_to_settings("error", "disabled")
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _back_to_settings("error", "signin_required")
    try:
        oauth.consume_state(db, state, user.id)
        if error:  # the user declined (or Meta refused) on the consent screen
            raise OAuthError("denied")
        grant = oauth.exchange_code(settings, code)
    except OAuthError as failure:
        logger.info("Instagram authorization not completed: %s", failure.code)
        return _back_to_settings("error", failure.code)
    connections.save_connection(
        db, TokenCipher.from_settings(settings), user_id=user.id,
        refresh_token=grant.refresh_token, account_id=grant.account_id,
        account_title=f"@{grant.username}" if grant.username else "",
        scopes=grant.scopes, provider=INSTAGRAM,
    )  # fmt: skip
    logger.info("Instagram authorization completed")
    return _back_to_settings("connected")


@router.delete("", response_model=DisconnectRead)
def disconnect_instagram(current_user: CurrentUser, db: DbSession) -> DisconnectRead:
    connection = connections.get_connection(db, current_user.id, INSTAGRAM)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No Instagram connection")
    settings = get_settings()
    cipher = (
        TokenCipher.from_settings(settings)
        if settings.publishing_token_encryption_key is not None
        else None
    )
    revoked = connections.disconnect(db, cipher, connection, oauth.revoke)
    return DisconnectRead(revoked_with_provider=revoked)
