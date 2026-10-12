"""Password hashing (Argon2id via pwdlib) and signed access tokens (PyJWT)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hasher.verify(password, password_hash)


# Verified against when a login email is unknown, so that lookups for missing and
# existing accounts take comparable time.
DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-equalisation")


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    """Return the user id from a valid, unexpired token, or None if it cannot be trusted."""
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None
