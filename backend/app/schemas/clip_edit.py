import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool

from app.services.clip_edit.config import AspectRatio, CaptionPosition, CaptionStyle, Layout


class EditRequest(BaseModel):
    """The only editing options a client can send. Unknown fields are rejected, and every
    value must come from an allow-list — no filters, fonts, paths, URLs or FFmpeg flags."""

    model_config = ConfigDict(extra="forbid")

    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    layout: Layout
    captions_enabled: StrictBool = False  # "yes"/1 are refused, not coerced
    caption_style: CaptionStyle | None = None
    caption_position: CaptionPosition | None = None
    # Required for layout "smart_reframe": a completed analysis of this clip (never a path).
    reframe_analysis_id: uuid.UUID | None = None


class ClipEditRead(BaseModel):
    """An edit variant. Never storage keys, paths, task ids or caption temp files."""

    id: uuid.UUID
    clip_id: uuid.UUID
    video_id: uuid.UUID
    status: str
    progress_percent: int
    attempt: int
    is_stale: bool
    configuration: dict[str, Any]
    aspect_ratio: str
    layout: str
    captions_enabled: bool
    caption_style: str | None
    caption_position: str | None
    reframe_analysis_id: uuid.UUID | None
    output_width: int
    output_height: int
    render_profile: str
    caption_cue_count: int | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    file_size: int | None
    video_codec: str | None
    audio_codec: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ClipEditPage(BaseModel):
    total: int
    offset: int
    limit: int
    edits: list[ClipEditRead]
