import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project


class VideoStatus(StrEnum):
    """Lifecycle of a source video in Milestone 2. Later milestones extend this."""

    UPLOADED = "uploaded"
    PROCESSING_METADATA = "processing_metadata"
    READY = "ready"
    FAILED = "failed"


class Video(Base):
    """A long-form source video uploaded to a project."""

    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )

    # What the user uploaded. The filename is metadata only and never used as a path.
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(BigInteger)

    # Filled in by metadata probing; absent until the video is ready.
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    video_codec: Mapped[str | None] = mapped_column(String(64))
    audio_codec: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(32), default=VideoStatus.UPLOADED)
    error_message: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="videos")

    def __repr__(self) -> str:
        return f"Video(id={self.id!r}, original_filename={self.original_filename!r}, status={self.status!r})"
