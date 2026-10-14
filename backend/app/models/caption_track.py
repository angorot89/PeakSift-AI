"""Word-timed captions: clip-local speech timing used by the dynamic caption renderer.

A ``CaptionTrack`` belongs to a ``Clip`` and describes *when each word was spoken* in that
clip — nothing about how captions look (that is the ``ClipEdit``'s configuration). The words
come from a speech-timing provider run on the clip's own audio (the exact artifact being
edited), so every ``CaptionWord`` carries real provider word timestamps: a track is always
"aligned word" timing. Phrase-timed captions (the V0.6 behaviour) are built from the
transcript at render time and are never stored here, so they cannot be mistaken for word
timing.

Times are clip-local seconds (``0`` = the first frame of the clip). ``(clip_id,
config_fingerprint)`` is unique, so repeating a request with the same server configuration
returns the existing track; a changed provider/model/version produces a new one.
``completed`` means the words were validated and written in the same transaction.
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


class CaptionTrackStatus(StrEnum):
    QUEUED = "queued"
    PREPARING_AUDIO = "preparing_audio"  # decoding the clip's audio
    ALIGNING = "aligning"  # the speech-timing provider is producing word timestamps
    VALIDATING = "validating"  # checking and normalizing the words
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_CAPTION_TRACK_STATUSES = (
    CaptionTrackStatus.QUEUED,
    CaptionTrackStatus.PREPARING_AUDIO,
    CaptionTrackStatus.ALIGNING,
    CaptionTrackStatus.VALIDATING,
)

MAX_WORD_LENGTH = 128


class CaptionTrack(Base):
    __tablename__ = "caption_tracks"
    __table_args__ = (
        UniqueConstraint("clip_id", "config_fingerprint", name="uq_caption_tracks_config"),
        CheckConstraint(
            "status IN ('queued', 'preparing_audio', 'aligning', 'validating', 'completed', "
            "'failed')",
            name="ck_caption_tracks_status",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_caption_tracks_progress"
        ),
        CheckConstraint("attempt >= 1", name="ck_caption_tracks_attempt"),
        CheckConstraint(
            "(word_count IS NULL OR word_count >= 0) "
            "AND (rejected_word_count IS NULL OR rejected_word_count >= 0)",
            name="ck_caption_tracks_counts",
        ),
        CheckConstraint(
            "average_confidence IS NULL OR (average_confidence >= 0 AND average_confidence <= 1)",
            name="ck_caption_tracks_confidence",
        ),
        CheckConstraint(
            "language_probability IS NULL "
            "OR (language_probability >= 0 AND language_probability <= 1)",
            name="ck_caption_tracks_language_probability",
        ),
        CheckConstraint(
            "audio_duration_seconds IS NULL OR audio_duration_seconds >= 0",
            name="ck_caption_tracks_audio_duration",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(32), default=CaptionTrackStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    # Server-chosen provider/model (never user input) and the snapshot the job runs with.
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    alignment_version: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    language_hint: Mapped[str | None] = mapped_column(String(16))

    # Results, written together with the words when the track completes.
    language: Mapped[str | None] = mapped_column(String(16))
    language_probability: Mapped[float | None] = mapped_column(Float)
    audio_duration_seconds: Mapped[float | None] = mapped_column(Float)
    word_count: Mapped[int | None] = mapped_column(Integer)
    # Words the provider returned without a usable interval (dropped, never invented).
    rejected_word_count: Mapped[int | None] = mapped_column(Integer)
    average_confidence: Mapped[float | None] = mapped_column(Float)

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

    clip: Mapped["Clip"] = relationship(back_populates="caption_tracks")
    words: Mapped[list["CaptionWord"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaptionWord.sequence_index",
    )

    def __repr__(self) -> str:
        return f"CaptionTrack(id={self.id!r}, clip_id={self.clip_id!r}, status={self.status!r})"


class CaptionWord(Base):
    """One spoken word with its provider timestamps, in clip-local seconds."""

    __tablename__ = "caption_words"
    __table_args__ = (
        UniqueConstraint("caption_track_id", "sequence_index", name="uq_caption_words_sequence"),
        CheckConstraint("sequence_index >= 0", name="ck_caption_words_sequence"),
        CheckConstraint("start_time >= 0", name="ck_caption_words_start"),
        CheckConstraint("end_time > start_time", name="ck_caption_words_interval"),
        CheckConstraint("length(text) > 0", name="ck_caption_words_text"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_caption_words_confidence",
        ),
        Index("ix_caption_words_track_time", "caption_track_id", "start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    caption_track_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("caption_tracks.id", ondelete="CASCADE")
    )
    sequence_index: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[float] = mapped_column(Float)  # clip-local seconds
    end_time: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(String(MAX_WORD_LENGTH))  # exactly as recognized
    confidence: Mapped[float | None] = mapped_column(Float)

    track: Mapped[CaptionTrack] = relationship(back_populates="words")
