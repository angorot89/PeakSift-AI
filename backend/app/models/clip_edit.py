"""Short-form edits: a derived 9:16 render of a generated clip, optionally with captions.

The V0.5 ``Clip`` stays the clean source cut and is never modified. A clip can have
several edits — one per distinct configuration: ``(clip_id, config_fingerprint)`` is
unique, so the same configuration requested twice (double click, network retry, two tabs)
resolves to the same edit, while a changed configuration creates a new variant.
``status`` describes the edited artifact: ``ready`` means a validated file exists at
``storage_key``.
"""

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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.clip import Clip


class ClipEditStatus(StrEnum):
    """Configuration is submitted atomically, so there is no draft state."""

    QUEUED = "queued"
    RENDERING = "rendering"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"


ACTIVE_CLIP_EDIT_STATUSES = (
    ClipEditStatus.QUEUED,
    ClipEditStatus.RENDERING,
    ClipEditStatus.VALIDATING,
)


class ClipEdit(Base):
    __tablename__ = "clip_edits"
    __table_args__ = (
        UniqueConstraint("clip_id", "config_fingerprint", name="uq_clip_edits_config"),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_clip_edits_progress"
        ),
        CheckConstraint("attempt >= 1", name="ck_clip_edits_attempt_positive"),
        CheckConstraint("output_width > 0 AND output_height > 0", name="ck_clip_edits_output"),
        CheckConstraint(
            "layout IN ('center_crop', 'blur_background', 'fit', 'smart_reframe', 'manual_crop')",
            name="ck_clip_edits_layout",
        ),
        CheckConstraint(
            # A manual crop has exactly one focal point inside the frame; other layouts none.
            "(layout = 'manual_crop' AND focus_x IS NOT NULL AND focus_y IS NOT NULL "
            "AND focus_x >= 0 AND focus_x <= 1 AND focus_y >= 0 AND focus_y <= 1) "
            "OR (layout <> 'manual_crop' AND focus_x IS NULL AND focus_y IS NULL)",
            name="ck_clip_edits_focus",
        ),
        CheckConstraint(
            # A smart reframe follows exactly one analysis; other layouts never reference one.
            "(layout = 'smart_reframe') = (reframe_analysis_id IS NOT NULL)",
            name="ck_clip_edits_reframe",
        ),
        CheckConstraint("aspect_ratio IN ('9:16')", name="ck_clip_edits_aspect_ratio"),
        CheckConstraint(
            # A hook has text, an allowed style and position and a bounded duration; no hook
            # has none of them.
            # Every term is NOT NULL-safe: a CHECK that evaluates to NULL would accept the row.
            "(hook_enabled AND hook_text IS NOT NULL AND length(hook_text) BETWEEN 1 AND 60 "
            "AND hook_style IS NOT NULL AND hook_style IN ('headline', 'boxed', 'minimal') "
            "AND hook_position IS NOT NULL AND hook_position IN ('top', 'center') "
            "AND hook_duration_seconds IS NOT NULL "
            "AND hook_duration_seconds >= 0.5 AND hook_duration_seconds <= 5) "
            "OR (NOT hook_enabled AND hook_text IS NULL AND hook_style IS NULL "
            "AND hook_position IS NULL AND hook_duration_seconds IS NULL)",
            name="ck_clip_edits_hook",
        ),
        CheckConstraint(
            # IS NOT NULL is explicit: "NULL IN (...)" is NULL, which a CHECK would accept.
            "(captions_enabled AND caption_style IS NOT NULL AND caption_position IS NOT NULL "
            "AND caption_position IN ('top', 'center', 'bottom') AND caption_renderer IS NOT NULL "
            "AND ((caption_renderer = 'caption_v1' "
            "AND caption_style IN ('clean', 'bold', 'creator')) "
            "OR (caption_renderer = 'caption_v2' "
            "AND caption_style IN ('focus', 'punch', 'minimal', 'boxed')))) "
            "OR (NOT captions_enabled AND caption_style IS NULL AND caption_position IS NULL "
            "AND caption_renderer IS NULL)",
            name="ck_clip_edits_captions",
        ),
        CheckConstraint(
            # Dynamic captions say how words are timed; word-synced ones name their track.
            "(caption_renderer = 'caption_v2' AND caption_timing IS NOT NULL "
            "AND caption_timing IN ('aligned_word', 'phrase_fallback') "
            "AND (caption_timing = 'aligned_word') = (caption_track_id IS NOT NULL)) "
            "OR (caption_renderer IS DISTINCT FROM 'caption_v2' "
            "AND caption_timing IS NULL AND caption_track_id IS NULL)",
            name="ck_clip_edits_caption_timing",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(32), default=ClipEditStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    # The normalized configuration snapshot and its fingerprint (see services/clip_edit/config).
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # V1.7, display only: the template and brand a version started from ({"template": {id, name,
    # version}, "brand": {name}, "auto_edit_plan_id"}). Never read by a render — the snapshot is.
    origin: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    # Queryable copies of the snapshot's fields (checked against the allow-lists).
    aspect_ratio: Mapped[str] = mapped_column(String(8))
    layout: Mapped[str] = mapped_column(String(32))
    captions_enabled: Mapped[bool] = mapped_column(Boolean)
    caption_style: Mapped[str | None] = mapped_column(String(32))
    caption_position: Mapped[str | None] = mapped_column(String(16))
    # caption_v1 (V0.6 phrase captions) or caption_v2 (V0.8 dynamic); None without captions.
    caption_renderer: Mapped[str | None] = mapped_column(String(16))
    caption_timing: Mapped[str | None] = mapped_column(String(16))
    # The exact word timing a word-synced edit was rendered from (never re-pointed later).
    caption_track_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("caption_tracks.id", ondelete="CASCADE"), index=True
    )
    # Smart reframe only: the completed analysis whose crop path this render follows.
    reframe_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reframe_analyses.id", ondelete="CASCADE"), index=True
    )
    # Manual crop only: the chosen focal point (fractions of the display-oriented source).
    focus_x: Mapped[float | None] = mapped_column(Float)
    focus_y: Mapped[float | None] = mapped_column(Float)
    # The optional opening hook overlay (V0.8).
    hook_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    hook_text: Mapped[str | None] = mapped_column(String(60))
    hook_style: Mapped[str | None] = mapped_column(String(16))
    hook_position: Mapped[str | None] = mapped_column(String(16))
    hook_duration_seconds: Mapped[float | None] = mapped_column(Float)
    output_width: Mapped[int] = mapped_column(Integer)
    output_height: Mapped[int] = mapped_column(Integer)
    render_profile: Mapped[str] = mapped_column(String(32))

    # Internal location of the final artifact; set only when ready. Never exposed.
    storage_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default="video/mp4")
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    # Validated output metadata (ffprobe), filled when ready.
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    video_codec: Mapped[str | None] = mapped_column(String(64))
    audio_codec: Mapped[str | None] = mapped_column(String(64))
    caption_cue_count: Mapped[int | None] = mapped_column(Integer)
    # Edits with an audio section: the encoded short's measured integrated loudness (LUFS) and
    # true peak (dBTP), recorded after rendering. Null for silent shorts and plain edits.
    audio_loudness_lufs: Mapped[float | None] = mapped_column(Float)
    audio_true_peak_dbtp: Mapped[float | None] = mapped_column(Float)

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

    clip: Mapped["Clip"] = relationship(back_populates="edits")

    def __repr__(self) -> str:
        return (
            f"ClipEdit(id={self.id!r}, clip_id={self.clip_id!r}, layout={self.layout!r}, "
            f"status={self.status!r})"
        )
