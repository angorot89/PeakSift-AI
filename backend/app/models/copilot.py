"""Creator Copilot conversations (V1.6).

A ``CopilotThread`` is one conversation: per creator and project (``project_id``), or one for the
creator's workspace (``project_id`` NULL — Home, Projects, Analytics, Settings). There is at
most one of each (partial unique indexes); the creator can clear a conversation at any time,
which deletes the thread and its messages and nothing else. Deleting the project or the user
deletes its threads (``ON DELETE CASCADE``).

A ``CopilotMessage`` keeps only what the creator saw: their question (``role='user'``) or the
assistant's final answer (``role='assistant'``) with its optional suggestion, the page it was
asked from, the actions offered (type, target and server-written label — re-validated before
any use) and the reference chips. Hidden reasoning, prompts and the context sent to the model
are never stored. ``status`` says whether the answer came from the local assistant (``ok``) or
PeakSift had to answer without it (``unavailable``).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

CONTENT_MAX_LENGTH = 4000


class CopilotRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class CopilotMessageStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"  # the local assistant could not answer; PeakSift said so


class CopilotThread(Base):
    __tablename__ = "copilot_threads"
    __table_args__ = (
        Index(
            "uq_copilot_threads_project", "user_id", "project_id", unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        Index(
            "uq_copilot_threads_workspace", "user_id", unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["CopilotMessage"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", passive_deletes=True,
        order_by="(CopilotMessage.created_at, CopilotMessage.sequence)",
    )  # fmt: skip

    def __repr__(self) -> str:
        return f"CopilotThread(id={self.id!r}, project_id={self.project_id!r})"


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_copilot_messages_role"),
        CheckConstraint("status IN ('ok', 'unavailable')", name="ck_copilot_messages_status"),
        CheckConstraint(
            f"length(content) BETWEEN 1 AND {CONTENT_MAX_LENGTH}",
            name="ck_copilot_messages_content",
        ),
        CheckConstraint("jsonb_typeof(actions) = 'array'", name="ck_copilot_messages_actions"),
        CheckConstraint("jsonb_typeof(refs) = 'array'", name="ck_copilot_messages_refs"),
        CheckConstraint("jsonb_typeof(cards) = 'array'", name="ck_copilot_messages_cards"),
        Index("ix_copilot_messages_thread_order", "thread_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("copilot_threads.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer)  # order within the thread (1, 2, …)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    page: Mapped[str] = mapped_column(String(32), default="home")
    status: Mapped[str] = mapped_column(String(16), default=CopilotMessageStatus.OK)
    # [{"type", "label", "target": {"kind", "id", "ref": {...}}, "query"?}] — re-validated on use.
    actions: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # [{"kind": "idea", "title", "time", "angle", "why", "style", "note", "action"}] — result
    # cards checked by the server (ideas only from real moments or transcript times).
    cards: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # [{"kind", "label"}] — creator-facing chips, never ids.
    refs: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    thread: Mapped[CopilotThread] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"CopilotMessage(id={self.id!r}, role={self.role!r})"
