"""A user's connection to a publishing provider (YouTube only).

The only secret kept is the OAuth **refresh token**, encrypted with AES-256-GCM before it is
stored (see ``app/services/publishing/tokens.py``); access tokens are short-lived and never
persisted. The ciphertext is bound to its user, provider and key version, so it is useless
copied to another row. One connection per user: reconnecting replaces it.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PublishingProvider(StrEnum):
    YOUTUBE = "youtube"


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    # Google refused the refresh token (revoked by the user, expired, password change): the
    # user must connect again; publishing is refused until then.
    NEEDS_RECONNECT = "needs_reconnect"


class PublishingConnection(Base):
    __tablename__ = "publishing_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_publishing_connections_user"),
        CheckConstraint("provider IN ('youtube')", name="ck_publishing_connections_provider"),
        CheckConstraint(
            "status IN ('connected', 'needs_reconnect')", name="ck_publishing_connections_status"
        ),
        CheckConstraint("token_key_version >= 1", name="ck_publishing_connections_key_version"),
        CheckConstraint(
            "length(refresh_token_ciphertext) > 28", name="ck_publishing_connections_ciphertext"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Unique (one connection per user), which also indexes it.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default=ConnectionStatus.CONNECTED)

    # The provider account the user authorized (YouTube channel): display information only.
    account_id: Mapped[str] = mapped_column(String(128))
    account_title: Mapped[str] = mapped_column(String(255))
    # Space-separated scopes the user actually granted.
    scopes: Mapped[str] = mapped_column(String(1024))

    # nonce (12 bytes) || AES-GCM ciphertext+tag; never returned, never logged.
    refresh_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    token_key_version: Mapped[int] = mapped_column(Integer)

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # never includes the ciphertext
        return (
            f"PublishingConnection(id={self.id!r}, provider={self.provider!r}, "
            f"status={self.status!r})"
        )
