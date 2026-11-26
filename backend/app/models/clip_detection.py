"""AI clip detection: a run analyses one transcript snapshot and produces ranked candidates.

A video may have many runs (different providers/models, re-runs after a new transcript)
but at most one *active* run at a time. Candidates are derived data: they point back to
the run, the video and the transcript fingerprint that produced them, so a candidate can
always be traced to the exact transcript it was generated from.
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
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.clip import Clip
    from app.models.transcription import Transcription
    from app.models.video import Video


class ClipDetectionStatus(StrEnum):
    """What is happening to the clip detection job (separate from video/transcription)."""

    QUEUED = "queued"
    PREPARING_TRANSCRIPT = "preparing_transcript"
    ANALYZING = "analyzing"
    VALIDATING = "validating"
    RANKING = "ranking"
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_CLIP_DETECTION_STATUSES = (
    ClipDetectionStatus.QUEUED,
    ClipDetectionStatus.PREPARING_TRANSCRIPT,
    ClipDetectionStatus.ANALYZING,
    ClipDetectionStatus.VALIDATING,
    ClipDetectionStatus.RANKING,
)

# SQL form of the active statuses, used by the one-active-run-per-video partial index.
_ACTIVE_STATUS_SQL = ", ".join(f"'{s.value}'" for s in ACTIVE_CLIP_DETECTION_STATUSES)


class CandidateOrigin(StrEnum):
    DETECTED = "detected"
    SEARCH = "search"


class CandidateDecision(StrEnum):
    UNDECIDED = "undecided"
    SAVED = "saved"
    DISMISSED = "dismissed"


# Editorial content types a candidate may be labelled with. Anything else becomes "other".
CANDIDATE_CATEGORIES = (
    "humor",
    "reaction",
    "story",
    "insight",
    "conflict",
    "emotional",
    "hot_take",
    "explanation",
    "other",
)

# Scores are integers on one documented 0–100 scale (editorial judgement, not a probability).
SCORE_MIN = 0
SCORE_MAX = 100

TITLE_MAX_LENGTH = 120
HOOK_MAX_LENGTH = 300
RATIONALE_MAX_LENGTH = 1000


def _score_check(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} >= {SCORE_MIN} AND {column} <= {SCORE_MAX}",
        name=f"ck_clip_candidates_{column}_range",
    )


class ClipDetectionRun(Base):
    """One AI analysis of a video's transcript. The database row is the job's source of truth."""

    __tablename__ = "clip_detection_runs"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_clip_detection_runs_progress",
        ),
        CheckConstraint("attempt >= 1", name="ck_clip_detection_runs_attempt_positive"),
        # At most one queued/running detection per video; completed and failed runs accumulate.
        Index(
            "uq_clip_detection_runs_one_active_per_video",
            "video_id",
            unique=True,
            postgresql_where=text(f"status IN ({_ACTIVE_STATUS_SQL})"),
        ),
        Index("ix_clip_detection_runs_video_created", "video_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    # The transcript this run read, pinned by id and by a fingerprint of its segments.
    transcription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcriptions.id", ondelete="CASCADE")
    )
    transcript_fingerprint: Mapped[str] = mapped_column(String(64))

    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    # Snapshot of the detection settings used (window size, clip bounds, target count…).
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    status: Mapped[str] = mapped_column(String(32), default=ClipDetectionStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    windows_total: Mapped[int | None] = mapped_column(Integer)
    windows_done: Mapped[int] = mapped_column(Integer, default=0)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    celery_task_id: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    video: Mapped["Video"] = relationship(back_populates="clip_detection_runs")
    transcription: Mapped["Transcription"] = relationship()
    candidates: Mapped[list["ClipCandidate"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClipCandidate.rank",
    )

    def __repr__(self) -> str:
        return (
            f"ClipDetectionRun(id={self.id!r}, video_id={self.video_id!r}, status={self.status!r})"
        )


class ClipCandidate(Base):
    """A ranked, explained moment proposed by a detection run (absolute seconds)."""

    __tablename__ = "clip_candidates"
    __table_args__ = (
        CheckConstraint("start_time >= 0", name="ck_clip_candidates_start_nonnegative"),
        CheckConstraint("end_time > start_time", name="ck_clip_candidates_end_after_start"),
        CheckConstraint(
            "abs(duration_seconds - (end_time - start_time)) < 0.01",
            name="ck_clip_candidates_duration_matches",
        ),
        CheckConstraint("rank >= 1", name="ck_clip_candidates_rank_positive"),
        CheckConstraint("origin IN ('detected', 'search')", name="ck_clip_candidates_origin"),
        _score_check("overall_score"),
        _score_check("hook_score"),
        _score_check("entertainment_score"),
        _score_check("clarity_score"),
        _score_check("payoff_score"),
        _score_check("completeness_score"),
        UniqueConstraint("run_id", "rank", name="uq_clip_candidates_rank"),
        Index("ix_clip_candidates_video_decision", "video_id", "decision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clip_detection_runs.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    duration_seconds: Mapped[float] = mapped_column(Float)

    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH))
    hook: Mapped[str] = mapped_column(String(HOOK_MAX_LENGTH))
    rationale: Mapped[str] = mapped_column(String(RATIONALE_MAX_LENGTH))
    category: Mapped[str] = mapped_column(String(32), default="other")
    # The real transcript text inside [start, end], copied from our segments — never model output.
    transcript_excerpt: Mapped[str] = mapped_column(Text, default="")

    overall_score: Mapped[int] = mapped_column(Integer)
    hook_score: Mapped[int] = mapped_column(Integer)
    entertainment_score: Mapped[int] = mapped_column(Integer)
    clarity_score: Mapped[int] = mapped_column(Integer)
    payoff_score: Mapped[int] = mapped_column(Integer)
    completeness_score: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int] = mapped_column(Integer)

    # Where the moment came from: "detected" by a run's analysis, or "search" — the creator
    # asked for it in plain language (Find Clips) and kept it. A searched moment carries the
    # request and no editorial scores (they are 0 and not shown).
    origin: Mapped[str] = mapped_column(
        String(16), default=CandidateOrigin.DETECTED, server_default=CandidateOrigin.DETECTED
    )
    query: Mapped[str | None] = mapped_column(String(200))

    decision: Mapped[str] = mapped_column(String(16), default=CandidateDecision.UNDECIDED)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    run: Mapped["ClipDetectionRun"] = relationship(back_populates="candidates")
    # The rendered artifact, once the user generates one (Milestone 5); at most one.
    clip: Mapped["Clip | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    def __repr__(self) -> str:
        return (
            f"ClipCandidate(rank={self.rank!r}, start_time={self.start_time!r}, "
            f"end_time={self.end_time!r}, overall_score={self.overall_score!r})"
        )
