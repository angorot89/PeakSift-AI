"""Single-use OAuth ``state`` for a connection in progress.

Created when a signed-in user starts connecting a provider, consumed (deleted) by the
callback in one atomic statement, and valid for ten minutes. It ties the callback to the
user who started it and carries the PKCE code verifier — encrypted like refresh tokens —
which never leaves the server. Only a hash of the state value is stored. ``purpose`` records
what the user was asked for — publishing (upload only) or the explicit analytics upgrade — so
the callback checks the grant against exactly that request.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.publishing_connection import PROVIDER_CHECK


class OAuthState(Base):
    __tablename__ = "oauth_states"
    __table_args__ = (
        CheckConstraint(PROVIDER_CHECK, name="ck_oauth_states_provider"),
        CheckConstraint("length(state_hash) = 64", name="ck_oauth_states_state_hash"),
        CheckConstraint("purpose IN ('publishing', 'analytics')", name="ck_oauth_states_purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(16), server_default="publishing")
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex of the state
    code_verifier_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"OAuthState(id={self.id!r}, provider={self.provider!r})"
