import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.services.audio_mix.config import MAX_SFX_CUES, DuckingStrength
from app.services.clip_edit.config import (
    AspectRatio,
    CaptionPosition,
    CaptionStyle,
    CaptionTiming,
    DynamicPreset,
    Layout,
)
from app.services.clip_edit.hook import HookPosition, HookStyle

Seconds = Annotated[float, Field(allow_inf_nan=False)]
Decibels = Annotated[float, Field(allow_inf_nan=False)]


class MusicRequest(BaseModel):
    """Background music from the project's audio. Bounds are checked by ``AudioMix``."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    gain_db: Decibels = -16.0
    source_start_seconds: Seconds = 0.0
    loop: StrictBool = True
    fade_in_seconds: Seconds = 0.5
    fade_out_seconds: Seconds = 1.0
    ducking: DuckingStrength = DuckingStrength.MEDIUM


class SfxCueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    at_seconds: Seconds  # in the edited short (clip-local time)
    gain_db: Decibels = -6.0


class AudioRequest(BaseModel):
    """Audio finishing: levels in dB, music, timed sound effects, final normalization."""

    model_config = ConfigDict(extra="forbid")

    source_gain_db: Decibels = 0.0
    normalize: StrictBool = True
    music: MusicRequest | None = None
    sfx: Annotated[list[SfxCueRequest], Field(max_length=MAX_SFX_CUES)] = []


class EditRequest(BaseModel):
    """The only editing options a client can send. Unknown fields are rejected, and every
    value must come from an allow-list — no filters, fonts, paths, URLs or FFmpeg flags."""

    model_config = ConfigDict(extra="forbid")

    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    layout: Layout
    captions_enabled: StrictBool = False  # "yes"/1 are refused, not coerced
    # Clean / Bold / Creator render with the V0.6 phrase renderer (caption_v1); Focus / Punch /
    # Minimal / Boxed with the dynamic word-aware renderer (caption_v2).
    caption_style: CaptionStyle | DynamicPreset | None = None
    caption_position: CaptionPosition | None = None
    # Dynamic captions only: "aligned_word" needs caption_track_id (a completed word timing
    # of this clip); "phrase_fallback" uses the transcript's phrase timing, never per word.
    caption_timing: CaptionTiming | None = None
    caption_track_id: uuid.UUID | None = None
    # Required for layout "smart_reframe": a completed analysis of this clip (never a path).
    reframe_analysis_id: uuid.UUID | None = None
    # Required for layout "manual_crop": the focal point, fractions of the frame (0..1).
    focus_x: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    focus_y: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    # The optional opening hook: plain text (escaped, never markup) and allow-listed options.
    hook_enabled: StrictBool = False
    hook_text: Annotated[str, Field(max_length=400)] | None = None
    hook_style: HookStyle | None = None
    hook_position: HookPosition | None = None
    hook_duration_seconds: Annotated[float, Field(allow_inf_nan=False)] | None = None
    # Optional audio finishing; omitted (or a section that changes nothing) keeps the clip's
    # own audio exactly as before.
    audio: AudioRequest | None = None


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
    caption_renderer: str | None
    caption_timing: str | None
    caption_track_id: uuid.UUID | None
    reframe_analysis_id: uuid.UUID | None
    focus_x: float | None
    focus_y: float | None
    hook_enabled: bool
    hook_text: str | None
    hook_style: str | None
    hook_position: str | None
    hook_duration_seconds: float | None
    output_width: int
    output_height: int
    render_profile: str
    caption_cue_count: int | None
    audio_loudness_lufs: float | None = None
    audio_true_peak_dbtp: float | None = None
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
