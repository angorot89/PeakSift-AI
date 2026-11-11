import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
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
    from app.models.project import Project


class AudioAssetKind(StrEnum):
    """What an uploaded sound is for: background music, or a short sound effect."""

    MUSIC = "music"
    SFX = "sfx"


class AudioAsset(Base):
    """A private, user-supplied audio file of one project (music or a sound effect).

    A row exists only for a validated upload: the file was probed (a real audio stream with
    a duration) and its waveform peaks were computed before the row was committed, and a
    failed upload leaves no file behind. The asset is never modified afterwards; edits
    reference it by id in their configuration snapshot.
    """

    __tablename__ = "audio_assets"
    __table_args__ = (
        # The same file uploaded twice for the same purpose in one project is one asset.
        UniqueConstraint("project_id", "kind", "sha256", name="uq_audio_assets_content"),
        CheckConstraint("kind IN ('music', 'sfx')", name="ck_audio_assets_kind"),
        CheckConstraint(
            "origin IN ('creator_upload', 'company_owned', 'licensed', 'public_domain', 'cc0')",
            name="ck_audio_assets_origin",
        ),
        CheckConstraint(
            "origin <> 'licensed' OR (license_note IS NOT NULL AND length(license_note) > 0)",
            name="ck_audio_assets_license_note",
        ),
        CheckConstraint("market IN ('global', 'ma')", name="ck_audio_assets_market"),
        CheckConstraint("length(display_name) > 0", name="ck_audio_assets_display_name"),
        CheckConstraint("file_size > 0", name="ck_audio_assets_file_size"),
        CheckConstraint("duration_seconds > 0", name="ck_audio_assets_duration"),
        CheckConstraint("sample_rate > 0", name="ck_audio_assets_sample_rate"),
        CheckConstraint("channels >= 1", name="ck_audio_assets_channels"),
        CheckConstraint("length(sha256) = 64", name="ck_audio_assets_sha256"),
        CheckConstraint("jsonb_typeof(waveform_peaks) = 'array'", name="ck_audio_assets_waveform"),
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
    sha256: Mapped[str] = mapped_column(String(64))

    # From ffprobe: the first audio stream and its container.
    container: Mapped[str] = mapped_column(String(64))
    codec: Mapped[str] = mapped_column(String(64))
    duration_seconds: Mapped[float] = mapped_column(Float)
    sample_rate: Mapped[int] = mapped_column(Integer)
    channels: Mapped[int] = mapped_column(Integer)

    # Bounded peak amplitudes (0-100 % of full scale) for a waveform display; never PCM.
    waveform_peaks: Mapped[list[Any]] = mapped_column(JSONB)

    # V1.8 labels (services/asset_labels.py), all chosen by the creator: how they have the right
    # to use it, whether it is local to a market, a category and — local only — a location.
    origin: Mapped[str] = mapped_column(
        String(16), default="creator_upload", server_default="creator_upload"
    )
    license_note: Mapped[str | None] = mapped_column(String(300))
    market: Mapped[str] = mapped_column(String(8), default="global", server_default="global")
    category: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="audio_assets")

    def __repr__(self) -> str:
        return f"AudioAsset(id={self.id!r}, kind={self.kind!r}, name={self.display_name!r})"
