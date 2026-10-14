"""Generated clips: the rendered MP4 artifact derived from one AI clip candidate.

A clip snapshots the candidate's validated boundaries at creation time so provenance is
kept even if the candidate changes later. One candidate has at most one clip (database
unique constraint); re-rendering a failed clip reuses the same row. ``status`` describes
the *rendered artifact* — ``ready`` means a validated file exists at ``storage_key`` —
and is independent of the video's or detection run's status.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.caption_track import CaptionTrack
    from app.models.clip_detection import ClipCandidate
    from app.models.clip_edit import ClipEdit
    from app.models.reframe import ReframeAnalysis
    from app.models.video import Video


class ClipStatus(StrEnum):
    """Health of the rendered artifact (separate from video and detection-run status)."""

    QUEUED = "queued"
    RENDERING = "rendering"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"


ACTIVE_CLIP_STATUSES = (ClipStatus.QUEUED, ClipStatus.RENDERING, ClipStatus.VALIDATING)

# The only render profile in V0.5: the source's aspect ratio and resolution, re-encoded to
# H.264/AAC in a fast-start MP4. Later profiles (vertical layouts, captions) get new names.
RENDER_PROFILE_SOURCE_MP4_V1 = "source_mp4_v1"

CLIP_CONTENT_TYPE = "video/mp4"


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_clips_progress"
        ),
        CheckConstraint("attempt >= 1", name="ck_clips_attempt_positive"),
        CheckConstraint("start_time >= 0", name="ck_clips_start_nonnegative"),
        CheckConstraint("end_time > start_time", name="ck_clips_end_after_start"),
        CheckConstraint(
            "abs(duration_seconds - (end_time - start_time)) < 0.01",
            name="ck_clips_duration_matches",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # One rendered clip per candidate in V0.5.
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clip_candidates.id", ondelete="CASCADE"), unique=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(32), default=ClipStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    # Snapshot of the candidate's validated boundaries (absolute seconds in the source).
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    duration_seconds: Mapped[float] = mapped_column(Float)

    render_profile: Mapped[str] = mapped_column(String(32), default=RENDER_PROFILE_SOURCE_MP4_V1)

    # Internal location of the final artifact; set only when status is ready. Never exposed.
    storage_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default=CLIP_CONTENT_TYPE)
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    # Validated output metadata (from ffprobe), filled when the clip becomes ready.
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    video_codec: Mapped[str | None] = mapped_column(String(64))
    audio_codec: Mapped[str | None] = mapped_column(String(64))

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

    candidate: Mapped["ClipCandidate"] = relationship(back_populates="clip")
    video: Mapped["Video"] = relationship(back_populates="clips")
    # Short-form edits derived from this clip (Milestone 6); the clip itself is never modified.
    edits: Mapped[list["ClipEdit"]] = relationship(
        back_populates="clip",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClipEdit.created_at.desc()",
    )
    reframe_analyses: Mapped[list["ReframeAnalysis"]] = relationship(
        back_populates="clip",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReframeAnalysis.created_at.desc()",
    )
    caption_tracks: Mapped[list["CaptionTrack"]] = relationship(
        back_populates="clip",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaptionTrack.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"Clip(id={self.id!r}, candidate_id={self.candidate_id!r}, status={self.status!r})"
