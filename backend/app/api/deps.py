from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User
from app.services.storage import StorageProvider, media_storage

DbSession = Annotated[Session, Depends(get_db)]


def get_storage() -> StorageProvider:
    """The configured media storage (``STORAGE_BACKEND``)."""
    return media_storage(get_settings())


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
