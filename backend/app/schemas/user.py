import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field


def _normalize_email(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


# Emails are stored and compared in lower case so "Me@Example.com" and "me@example.com"
# are the same account.
NormalizedEmail = Annotated[EmailStr, BeforeValidator(_normalize_email)]

Password = Annotated[str, Field(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    email: NormalizedEmail
    password: Password


class UserLogin(BaseModel):
    email: NormalizedEmail
    password: Annotated[str, Field(max_length=128)]


class UserRead(BaseModel):
    """Public representation of a user. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime
