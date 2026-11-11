from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.config import get_settings
from app.core.rate_limit import enforce, per_ip
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.user import PreferencesUpdate, SessionRead, UserCreate, UserLogin, UserRead
from app.services import markets

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
        secure=settings.cookie_secure,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    dependencies=[per_ip("register_ip")],
)
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


@router.post("/login", response_model=UserRead, dependencies=[per_ip("login_ip")])
def login(payload: UserLogin, response: Response, db: DbSession) -> User:
    # Per account too: spreading guesses over many addresses does not help.
    enforce("login_account", payload.email.lower())
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
        secure=settings.cookie_secure,
    )


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> User:
    return current_user


@router.patch("/me", response_model=UserRead)
def update_preferences(body: PreferencesUpdate, current_user: CurrentUser, db: DbSession) -> User:
    """Change the creator's preferences (the default market for new projects)."""
    if body.default_market is not None:
        try:
            current_user.default_market = markets.market(body.default_market).code
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown market"
            ) from None
    db.commit()
    return current_user


@router.get("/session", response_model=SessionRead)
def session(user: OptionalUser) -> SessionRead:
    """The signed-in user or null, always 200 (the app's start-up check; ``/me`` keeps its 401)."""
    return SessionRead(user=UserRead.model_validate(user) if user else None)
