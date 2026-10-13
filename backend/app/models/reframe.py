"""Smart reframing: a face-aware 9:16 crop path computed for a generated clip.

A ``ReframeAnalysis`` belongs to a ``Clip`` (geometry belongs to the clip, not to caption
styling). ``(clip_id, config_fingerprint)`` is unique, so re-requesting the same analysis
returns the existing row instead of duplicating work; a changed server configuration or
algorithm version produces a new analysis.

The result is a sparse, ordered list of ``ReframeKeyframe`` rows — crop centres and sizes at
sampled timestamps — that the browser preview and the renderer interpolate between. Geometry
is normalized to the display-oriented source frame (see ``services/reframe/config.py``).
``completed`` means a validated path exists; it is written in the same transaction.
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


class ReframeStatus(StrEnum):
    QUEUED = "queued"
    SAMPLING = "sampling"  # decoding downscaled frames from the clip
    DETECTING = "detecting"  # running the face detector over the samples
    TRACKING = "tracking"  # linking detections over time, choosing the subject
    PLANNING = "planning"  # computing the smoothed crop path
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_REFRAME_STATUSES = (
    ReframeStatus.QUEUED,
    ReframeStatus.SAMPLING,
    ReframeStatus.DETECTING,
    ReframeStatus.TRACKING,
    ReframeStatus.PLANNING,
)


class ReframeConfidence(StrEnum):
    """Plain-language summary of a path (documented thresholds, not a probability)."""

    HIGH = "high"  # a subject was followed for most of the clip
    MIXED = "mixed"  # tracked in parts, centre fallback in others
    FALLBACK = "fallback"  # little or no usable subject: mostly centre framing


class KeyframeMode(StrEnum):
    TRACKED = "tracked"  # following one subject
    GROUP = "group"  # framing two subjects that fit together
    FALLBACK = "fallback"  # centre framing (no reliable subject)


class ReframeAnalysis(Base):
    __tablename__ = "reframe_analyses"
    __table_args__ = (
        UniqueConstraint("clip_id", "config_fingerprint", name="uq_reframe_analyses_config"),
        CheckConstraint(
            "status IN ('queued', 'sampling', 'detecting', 'tracking', 'planning', "
            "'completed', 'failed')",
            name="ck_reframe_analyses_status",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_reframe_analyses_progress"
        ),
        CheckConstraint("attempt >= 1", name="ck_reframe_analyses_attempt"),
        CheckConstraint("sample_fps > 0", name="ck_reframe_analyses_sample_fps"),
        CheckConstraint("target_aspect_ratio IN ('9:16')", name="ck_reframe_analyses_ratio"),
        CheckConstraint(
            "(source_width IS NULL AND source_height IS NULL) "
            "OR (source_width IS NOT NULL AND source_height IS NOT NULL "
            "AND source_width > 0 AND source_height > 0)",
            name="ck_reframe_analyses_source_size",
        ),
        CheckConstraint(
            "overall_confidence IS NULL OR (overall_confidence >= 0 AND overall_confidence <= 1)",
            name="ck_reframe_analyses_confidence",
        ),
        CheckConstraint(
            "confidence_level IS NULL OR confidence_level IN ('high', 'mixed', 'fallback')",
            name="ck_reframe_analyses_confidence_level",
        ),
        CheckConstraint(
            "fallback_fraction IS NULL OR (fallback_fraction >= 0 AND fallback_fraction <= 1)",
            name="ck_reframe_analyses_fallback_fraction",
        ),
        CheckConstraint(
            "(frames_sampled IS NULL OR frames_sampled >= 0) "
            "AND (detections_count IS NULL OR detections_count >= 0) "
            "AND (tracks_count IS NULL OR tracks_count >= 0) "
            "AND (subject_switches IS NULL OR subject_switches >= 0)",
            name="ck_reframe_analyses_counts",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(32), default=ReframeStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    # Server-chosen detector (never user input) and the configuration snapshot it ran with.
    provider: Mapped[str] = mapped_column(String(64))
    provider_version: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    sample_fps: Mapped[float] = mapped_column(Float)
    target_aspect_ratio: Mapped[str] = mapped_column(String(8), default="9:16")

    # Display-oriented source size (after rotation), recorded when sampling starts.
    source_width: Mapped[int | None] = mapped_column(Integer)
    source_height: Mapped[int | None] = mapped_column(Integer)

    # Results and diagnostics, filled together with the keyframes when completed.
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    confidence_level: Mapped[str | None] = mapped_column(String(16))
    frames_sampled: Mapped[int | None] = mapped_column(Integer)
    detections_count: Mapped[int | None] = mapped_column(Integer)
    tracks_count: Mapped[int | None] = mapped_column(Integer)
    subject_switches: Mapped[int | None] = mapped_column(Integer)
    fallback_fraction: Mapped[float | None] = mapped_column(Float)

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

    clip: Mapped["Clip"] = relationship(back_populates="reframe_analyses")
    keyframes: Mapped[list["ReframeKeyframe"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReframeKeyframe.sequence_index",
    )

    def __repr__(self) -> str:
        return f"ReframeAnalysis(id={self.id!r}, clip_id={self.clip_id!r}, status={self.status!r})"


class ReframeKeyframe(Base):
    """One point of the crop path: the crop centre and size at a clip-local timestamp."""

    __tablename__ = "reframe_keyframes"
    __table_args__ = (
        UniqueConstraint(
            "reframe_analysis_id", "sequence_index", name="uq_reframe_keyframes_sequence"
        ),
        CheckConstraint("sequence_index >= 0", name="ck_reframe_keyframes_sequence"),
        CheckConstraint("timestamp >= 0", name="ck_reframe_keyframes_timestamp"),
        CheckConstraint(
            "center_x >= 0 AND center_x <= 1 AND center_y >= 0 AND center_y <= 1",
            name="ck_reframe_keyframes_center",
        ),
        CheckConstraint(
            "crop_width > 0 AND crop_width <= 1 AND crop_height > 0 AND crop_height <= 1",
            name="ck_reframe_keyframes_size",
        ),
        # The crop must lie inside the source: centre ± half size within [0, 1] (with a
        # tolerance for floating-point rounding of values that were clamped exactly).
        CheckConstraint(
            "center_x - crop_width / 2 >= -0.000001 AND center_x + crop_width / 2 <= 1.000001 "
            "AND center_y - crop_height / 2 >= -0.000001 "
            "AND center_y + crop_height / 2 <= 1.000001",
            name="ck_reframe_keyframes_inside",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_reframe_keyframes_confidence"
        ),
        CheckConstraint(
            "mode IN ('tracked', 'group', 'fallback')", name="ck_reframe_keyframes_mode"
        ),
        Index("ix_reframe_keyframes_analysis_time", "reframe_analysis_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reframe_analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reframe_analyses.id", ondelete="CASCADE")
    )
    sequence_index: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[float] = mapped_column(Float)  # clip-local seconds
    center_x: Mapped[float] = mapped_column(Float)
    center_y: Mapped[float] = mapped_column(Float)
    crop_width: Mapped[float] = mapped_column(Float)
    crop_height: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(16))

    analysis: Mapped[ReframeAnalysis] = relationship(back_populates="keyframes")
