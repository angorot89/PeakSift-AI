import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TranscriptionRead(BaseModel):
    """Job status. Polling-friendly: no transcript text, no internals (task ids, paths)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    status: str
    provider: str
    model: str
    language: str | None
    language_probability: float | None
    progress_percent: int
    segment_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TranscriptSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence_index: int
    start: float
    end: float
    text: str
    speaker: str | None


class TranscriptPage(BaseModel):
    transcription_id: uuid.UUID
    total: int
    offset: int
    limit: int
    segments: list[TranscriptSegmentRead]
    # Only present when requested with ?include_text=true, never on every page.
    full_text: str | None = None
