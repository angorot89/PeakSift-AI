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


def get_optional_user(request: Request, db: DbSession) -> User | None:
    """The user of a valid auth cookie, or None (no cookie, bad token or unknown user)."""
    token = request.cookies.get(get_settings().auth_cookie_name)
    if not token:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    return db.get(User, user_id)


def get_current_user(request: Request, db: DbSession) -> User:
    """Resolve the user from the auth cookie, or fail with 401."""
    user = get_optional_user(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
