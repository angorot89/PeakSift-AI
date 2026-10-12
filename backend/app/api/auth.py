from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.user import UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_TAKEN = "An account with this email already exists"
INVALID_CREDENTIALS = "Invalid email or password"


def _set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserRead)
def register(payload: UserCreate, response: Response, db: DbSession) -> User:
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EMAIL_TAKEN)

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent registration for the same email.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EMAIL_TAKEN) from None

    _set_auth_cookie(response, create_access_token(user.id))
    return user


@router.post("/login", response_model=UserRead)
def login(payload: UserLogin, response: Response, db: DbSession) -> User:
    user = db.scalar(select(User).where(User.email == payload.email))

    if user is None:
        # Spend the same time as a real check so timing does not reveal unknown emails.
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)

    _set_auth_cookie(response, create_access_token(user.id))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> User:
    return current_user
