import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
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
    from app.models.project import Project


class VisualAssetKind(StrEnum):
    """What a creator-supplied visual is: a still image, or a video clip (B-roll)."""

    IMAGE = "image"
    VIDEO = "video"


class VisualAsset(Base):
    """A private, creator-supplied image or video of one project, for B-roll and overlays.

    As with audio assets, a row exists only for a validated upload: the file was inspected
    (decoded image or probed video with real dimensions), its thumbnail was generated and
    both objects were stored before the row was committed; a refused upload leaves nothing
    behind. Images are stored as a normalized rendition (upright, RGB or RGBA, metadata
    stripped), so every later step sees exactly the pixels the creator saw. The asset is never
    modified afterwards except for its descriptive metadata (name, description, tags); edits
    reference it by id.

    Dimensions are *display* dimensions — after rotation and sample aspect ratio — so a
    portrait phone video is taller than it is wide here, whatever its coded size.
    """

    __tablename__ = "visual_assets"
    __table_args__ = (
        # The same file uploaded twice to one project is one asset.
        UniqueConstraint("project_id", "sha256", name="uq_visual_assets_content"),
        CheckConstraint("kind IN ('image', 'video')", name="ck_visual_assets_kind"),
        CheckConstraint("length(display_name) > 0", name="ck_visual_assets_display_name"),
        CheckConstraint("file_size > 0", name="ck_visual_assets_file_size"),
        CheckConstraint("width > 0 AND height > 0", name="ck_visual_assets_dimensions"),
        CheckConstraint("length(sha256) = 64", name="ck_visual_assets_sha256"),
        CheckConstraint("length(description) <= 500", name="ck_visual_assets_description"),
        CheckConstraint("jsonb_typeof(tags) = 'array'", name="ck_visual_assets_tags"),
        # Images have no duration, frame rate or audio; videos have a positive duration.
        CheckConstraint(
            "(kind = 'image' AND duration_seconds IS NULL AND fps IS NULL AND NOT has_audio) "
            "OR (kind = 'video' AND duration_seconds IS NOT NULL AND duration_seconds > 0 "
            "AND (fps IS NULL OR fps > 0) "
            "AND NOT has_alpha)",
            name="ck_visual_assets_kind_metadata",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))

    # The uploaded name, sanitized: display metadata only, never a filesystem path.
    display_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(BigInteger)
    # sha256 of the uploaded bytes (duplicate detection within the project).
    sha256: Mapped[str] = mapped_column(String(64))

    # Inspection results (Pillow for images, ffprobe for videos).
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    codec: Mapped[str] = mapped_column(String(64))
    container: Mapped[str] = mapped_column(String(64))
    # Images only: whether any pixel is transparent (overlays keep it).
    has_alpha: Mapped[bool] = mapped_column(Boolean, default=False)
    # Videos only: whether the file carries sound. B-roll is always rendered muted.
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional creator-written words that help match B-roll suggestions (never sent anywhere).
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    tags: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))

    # A small preview image (bounded size), stored next to the asset in private storage.
    thumbnail_storage_key: Mapped[str | None] = mapped_column(String(255), unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="visual_assets")

    @property
    def has_thumbnail(self) -> bool:
        return self.thumbnail_storage_key is not None

    @property
    def storage_keys(self) -> list[str]:
        """Every object this asset owns."""
        thumbnail = [self.thumbnail_storage_key] if self.thumbnail_storage_key else []
        return [self.storage_key, *thumbnail]

    def __repr__(self) -> str:
        return f"VisualAsset(id={self.id!r}, kind={self.kind!r}, name={self.display_name!r})"
