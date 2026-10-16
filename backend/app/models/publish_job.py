"""Publishing one ready edited short to YouTube.

A job is the user's explicit request to upload one READY edit with the metadata they
reviewed (title, description, tags, privacy — private by default, "made for kids"). It
moves ``queued → preparing → uploading → uploaded → processing → published``; ``failed``
means PeakSift could not finish (retryable), ``provider_failed`` that YouTube rejected or
could not process the video. The resumable upload session URI is a secret: stored only
encrypted, never returned. ``fingerprint`` makes the request idempotent: the same edit,
connection and metadata return the existing job instead of uploading twice.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PublishStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"  # YouTube has every byte and returned a video id
    PROCESSING = "processing"  # YouTube is processing it
    PUBLISHED = "published"  # processed and available at the chosen privacy
    FAILED = "failed"  # PeakSift could not finish; safe to retry
    PROVIDER_FAILED = "provider_failed"  # YouTube rejected or could not process the video


class Privacy(StrEnum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


ACTIVE_PUBLISH_STATUSES = (
    PublishStatus.QUEUED,
    PublishStatus.PREPARING,
    PublishStatus.UPLOADING,
)
FINISHED_UPLOAD_STATUSES = (
    PublishStatus.UPLOADED,
    PublishStatus.PROCESSING,
    PublishStatus.PUBLISHED,
)


class PublishJob(Base):
    __tablename__ = "publish_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_publish_jobs_fingerprint"),
        UniqueConstraint("provider_video_id", name="uq_publish_jobs_provider_video"),
        CheckConstraint("provider IN ('youtube')", name="ck_publish_jobs_provider"),
        CheckConstraint(
            "status IN ('queued', 'preparing', 'uploading', 'uploaded', 'processing', "
            "'published', 'failed', 'provider_failed')",
            name="ck_publish_jobs_status",
        ),
        CheckConstraint(
            "privacy IN ('private', 'unlisted', 'public')", name="ck_publish_jobs_privacy"
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 100", name="ck_publish_jobs_title_length"
        ),
        CheckConstraint(
            "octet_length(description) <= 5000", name="ck_publish_jobs_description_length"
        ),
        CheckConstraint("jsonb_typeof(tags) = 'array'", name="ck_publish_jobs_tags"),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_publish_jobs_progress"
        ),
        CheckConstraint("attempt >= 1", name="ck_publish_jobs_attempt"),
        CheckConstraint(
            "bytes_uploaded >= 0 AND (bytes_total IS NULL OR bytes_uploaded <= bytes_total)",
            name="ck_publish_jobs_bytes",
        ),
        CheckConstraint(
            "status NOT IN ('uploaded', 'processing', 'published') "
            "OR provider_video_id IS NOT NULL",
            name="ck_publish_jobs_video_id",
        ),
        CheckConstraint("length(fingerprint) = 64", name="ck_publish_jobs_fingerprint_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    edit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clip_edits.id", ondelete="CASCADE"), index=True
    )
    # Which connection it was published through; kept when the user disconnects later.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("publishing_connections.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(16))

    # The metadata the user reviewed, exactly as sent to YouTube (validated, never truncated).
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    privacy: Mapped[str] = mapped_column(String(16), default=Privacy.PRIVATE)
    made_for_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    category_id: Mapped[str] = mapped_column(String(8))
    fingerprint: Mapped[str] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(32), default=PublishStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    bytes_total: Mapped[int | None] = mapped_column(BigInteger)
    bytes_uploaded: Mapped[int] = mapped_column(BigInteger, default=0)

    # The resumable session URI (a bearer secret for the upload): encrypted, internal.
    upload_session_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    upload_session_key_version: Mapped[int | None] = mapped_column(Integer)
    upload_session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    provider_video_id: Mapped[str | None] = mapped_column(String(64))
    provider_upload_status: Mapped[str | None] = mapped_column(String(32))
    provider_processing_status: Mapped[str | None] = mapped_column(String(32))

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
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # never includes the session or metadata text
        return f"PublishJob(id={self.id!r}, status={self.status!r})"
