import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("default_market IN ('global', 'ma')", name="ck_users_default_market"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Where new projects are made for by default (a preference: never changes existing projects).
    default_market: Mapped[str] = mapped_column(
        String(8), default="global", server_default="global"
    )
    # Posting times (Schedule & Post): the weekly slots the creator likes to post at, as
    # [{"weekday": 0-6 (Monday first), "time": "HH:MM"}] in ``posting_timezone`` (an IANA name).
    # A preference only: nothing is ever scheduled from it without the creator choosing to.
    posting_slots: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    posting_timezone: Mapped[str | None] = mapped_column(String(64))

    projects: Mapped[list["Project"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, email={self.email!r})"
