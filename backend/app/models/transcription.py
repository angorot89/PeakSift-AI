import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.video import Video


class TranscriptionStatus(StrEnum):
    """What is happening to the speech-to-text job (separate from the video's status)."""

    QUEUED = "queued"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_TRANSCRIPTION_STATUSES = (
    TranscriptionStatus.QUEUED,
    TranscriptionStatus.EXTRACTING_AUDIO,
    TranscriptionStatus.TRANSCRIBING,
)


class Transcription(Base):
    """The one current transcription job for a video, plus its result."""

    __tablename__ = "transcriptions"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_transcriptions_progress"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # One current transcription per video (Milestone 3 keeps no history).
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), unique=True
    )

    status: Mapped[str] = mapped_column(String(32), default=TranscriptionStatus.QUEUED)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))

    language: Mapped[str | None] = mapped_column(String(16))
    language_probability: Mapped[float | None] = mapped_column(Float)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    full_text: Mapped[str | None] = mapped_column(Text)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    # Quick start: when this transcript completes, the worker starts moment detection with
    # the server's default provider (once; see clip_detection/autostart.py).
    auto_find_moments: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # Internal metadata about derived audio; never exposed by the API.
    audio_storage_key: Mapped[str | None] = mapped_column(String(255))
    audio_duration_seconds: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    video: Mapped["Video"] = relationship(back_populates="transcription")
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcription",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TranscriptSegment.sequence_index",
    )

    def __repr__(self) -> str:
        return f"Transcription(id={self.id!r}, video_id={self.video_id!r}, status={self.status!r})"


class TranscriptSegment(Base):
    """One timestamped piece of transcript text, in absolute seconds from the video start."""

    __tablename__ = "transcript_segments"
    __table_args__ = (
        CheckConstraint("start_time >= 0", name="ck_transcript_segments_start_nonnegative"),
        CheckConstraint("end_time > start_time", name="ck_transcript_segments_end_after_start"),
        UniqueConstraint("transcription_id", "sequence_index", name="uq_transcript_segments_order"),
        Index("ix_transcript_segments_transcription_start", "transcription_id", "start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transcription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcriptions.id", ondelete="CASCADE"), index=True
    )
    sequence_index: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    # Reserved for future diarization; always NULL in Milestone 3.
    speaker: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transcription: Mapped["Transcription"] = relationship(back_populates="segments")

    def __repr__(self) -> str:
        return (
            f"TranscriptSegment(sequence_index={self.sequence_index!r}, "
            f"start_time={self.start_time!r}, end_time={self.end_time!r})"
        )
