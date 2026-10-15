from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User
from app.services.storage import StorageProvider, storage_from_settings

DbSession = Annotated[Session, Depends(get_db)]


_provider: tuple[Settings, StorageProvider] | None = None


def get_storage() -> StorageProvider:
    """The configured media storage (``STORAGE_BACKEND``), built once per settings object:
    an S3 client is thread-safe and costly to create."""
    global _provider
    settings = get_settings()
    if _provider is None or _provider[0] is not settings:
        _provider = (settings, storage_from_settings(settings))
    return _provider[1]


Storage = Annotated[StorageProvider, Depends(get_storage)]


def get_current_user(request: Request, db: DbSession) -> User:
    """Resolve the user from the auth cookie, or fail with 401."""
    unauthenticated = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
    )

    token = request.cookies.get(get_settings().auth_cookie_name)
    if not token:
        raise unauthenticated

    user_id = decode_access_token(token)
    if user_id is None:
        raise unauthenticated

    user = db.get(User, user_id)
    if user is None:
        raise unauthenticated
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
