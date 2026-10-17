"""B-roll suggestions: *what* visual would help at a moment of a clip — never where to get it.

A ``BrollAnalysis`` belongs to a ``Clip`` and records one run of the suggestion job (status,
attempts, the server configuration it ran with). Its ``BrollSuggestion`` rows each describe a
short interval of the clip (clip-local seconds), a plain-language *query* ("Moon / spacecraft
footage") and the *reason* grounded in what was said. A suggestion never names a source, URL
or asset: creators match it to their own uploads (or ignore it).

``(clip_id, config_fingerprint)`` is unique, so asking again with the same server
configuration returns the existing analysis; regenerating deliberately bumps ``generation`` in
the configuration, which creates a new analysis. Suggestion status (suggested, accepted,
dismissed) is the creator's decision and never changes what is rendered by itself.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.clip import Clip


class BrollAnalysisStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"  # the suggestion provider is reading the transcript
    VALIDATING = "validating"  # checking, grounding and de-duplicating its answer
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_BROLL_ANALYSIS_STATUSES = (
    BrollAnalysisStatus.QUEUED,
    BrollAnalysisStatus.ANALYZING,
    BrollAnalysisStatus.VALIDATING,
)


class BrollSuggestionStatus(StrEnum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"  # the creator used it (matched an asset)
    DISMISSED = "dismissed"  # the creator does not want it


QUERY_MAX_LENGTH = 120
REASON_MAX_LENGTH = 300
SCORE_MIN, SCORE_MAX = 0, 100


class BrollAnalysis(Base):
    __tablename__ = "broll_analyses"
    __table_args__ = (
        UniqueConstraint("clip_id", "config_fingerprint", name="uq_broll_analyses_config"),
        CheckConstraint(
            "status IN ('queued', 'analyzing', 'validating', 'completed', 'failed')",
            name="ck_broll_analyses_status",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_broll_analyses_progress"
        ),
        CheckConstraint("attempt >= 1", name="ck_broll_analyses_attempt"),
        CheckConstraint("generation >= 1", name="ck_broll_analyses_generation"),
        CheckConstraint(
            "(suggestion_count IS NULL OR suggestion_count >= 0) "
            "AND (rejected_count IS NULL OR rejected_count >= 0)",
            name="ck_broll_analyses_counts",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(32), default=BrollAnalysisStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    # The server configuration snapshot the job runs with (never user input) and its
    # fingerprint; ``generation`` > 1 marks a deliberate regeneration.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    suggestion_version: Mapped[str] = mapped_column(String(32))
    # Who produced the suggestions: the configured provider, or the deterministic fallback
    # when the configured one was unavailable (``fallback_reason`` then says why).
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    fallback_reason: Mapped[str | None] = mapped_column(String(64))

    clip_duration_seconds: Mapped[float | None] = mapped_column(Float)
    suggestion_count: Mapped[int | None] = mapped_column(Integer)
    # Raw proposals refused by validation (bad timing, ungrounded, vague, duplicate, too dense).
    rejected_count: Mapped[int | None] = mapped_column(Integer)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    # Attempt-ownership token (fencing), committed before the job is enqueued. Internal.
    celery_task_id: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    clip: Mapped["Clip"] = relationship(back_populates="broll_analyses")
    suggestions: Mapped[list["BrollSuggestion"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BrollSuggestion.sequence_index",
    )

    def __repr__(self) -> str:
        return f"BrollAnalysis(id={self.id!r}, clip_id={self.clip_id!r}, status={self.status!r})"


class BrollSuggestion(Base):
    """One suggested visual moment, in clip-local seconds."""

    __tablename__ = "broll_suggestions"
    __table_args__ = (
        UniqueConstraint("analysis_id", "sequence_index", name="uq_broll_suggestions_sequence"),
        CheckConstraint("sequence_index >= 0", name="ck_broll_suggestions_sequence"),
        CheckConstraint("start_time >= 0", name="ck_broll_suggestions_start"),
        CheckConstraint("end_time > start_time", name="ck_broll_suggestions_interval"),
        CheckConstraint("length(query) > 0", name="ck_broll_suggestions_query"),
        CheckConstraint("length(reason) > 0", name="ck_broll_suggestions_reason"),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)", name="ck_broll_suggestions_score"
        ),
        CheckConstraint(
            "status IN ('suggested', 'accepted', 'dismissed')", name="ck_broll_suggestions_status"
        ),
        Index("ix_broll_suggestions_analysis_time", "analysis_id", "start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("broll_analyses.id", ondelete="CASCADE")
    )
    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="CASCADE"), index=True
    )
    sequence_index: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[float] = mapped_column(Float)  # clip-local seconds
    end_time: Mapped[float] = mapped_column(Float)
    query: Mapped[str] = mapped_column(String(QUERY_MAX_LENGTH))
    reason: Mapped[str] = mapped_column(String(REASON_MAX_LENGTH))
    score: Mapped[int | None] = mapped_column(Integer)  # 0-100 editorial, never a prediction
    status: Mapped[str] = mapped_column(String(16), default=BrollSuggestionStatus.SUGGESTED)
    provider: Mapped[str] = mapped_column(String(64))
    provider_version: Mapped[str] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    analysis: Mapped[BrollAnalysis] = relationship(back_populates="suggestions")

    def __repr__(self) -> str:
        return (
            f"BrollSuggestion(id={self.id!r}, {self.start_time:.2f}-{self.end_time:.2f}s, "
            f"query={self.query!r}, status={self.status!r})"
        )
