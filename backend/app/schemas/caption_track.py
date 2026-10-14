"""Caption-track responses. Never task ids, fingerprints, paths, model locations or commands."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.model_name import PublicModelName


class CaptionTrackRead(BaseModel):
    id: uuid.UUID
    clip_id: uuid.UUID
    status: str
    progress_percent: int
    attempt: int
    is_stale: bool
    # A track is always real provider word timing; phrase timing is never stored as a track.
    timing_mode: Literal["aligned_word"] = "aligned_word"
    provider: str
    model: PublicModelName
    language: str | None
    word_count: int | None
    rejected_word_count: int | None
    average_confidence: float | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CaptionTrackPage(BaseModel):
    total: int
    tracks: list[CaptionTrackRead]


class CaptionWordRead(BaseModel):
    """One word, clip-local seconds (``i`` is its order in the track)."""

    i: int
    start: float
    end: float
    text: str
    confidence: float | None


class CaptionWordsRead(BaseModel):
    track_id: uuid.UUID
    timing_mode: Literal["aligned_word"] = "aligned_word"
    language: str | None
    words: list[CaptionWordRead]


class CaptionTimingOptions(BaseModel):
    """What captions of this clip can be timed with, in plain terms for the editor."""

    # aligned_word: real word timestamps from the clip's audio (needs a completed track).
    word_timing: Literal["none", "running", "completed", "failed"]
    track: CaptionTrackRead | None
    # phrase_fallback: segment-level transcript timing (the V0.6 behaviour); never per word.
    phrase_timing_available: bool


class CaptionPreviewWord(BaseModel):
    text: str  # as the burned-in caption shows it (emoji left out where the server cannot draw)
    start: float  # active from (clip-local seconds)
    end: float  # active until
    attached: bool  # a later piece of a split token: no space before it


class CaptionPreviewCue(BaseModel):
    start: float
    end: float
    timed: bool  # word-synced: emphasise the active word; phrase-timed: never
    lines: list[list[CaptionPreviewWord]]


class CaptionPreviewRead(BaseModel):
    """The dynamic caption text exactly as the renderer lays it out (same cues, lines, timing)."""

    timing: Literal["aligned_word", "phrase_fallback"]
    emoji: Literal["monochrome", "omitted"]
    cues: list[CaptionPreviewCue]
