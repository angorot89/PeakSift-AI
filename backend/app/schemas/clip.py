import uuid
from datetime import datetime

from pydantic import BaseModel


class ClipRead(BaseModel):
    """A generated clip. Polling-friendly; never storage keys, paths or task ids."""

    id: uuid.UUID
    candidate_id: uuid.UUID
    run_id: uuid.UUID
    video_id: uuid.UUID
    title: str  # the candidate's title, for display
    status: str
    progress_percent: int
    attempt: int
    is_stale: bool
    start_time: float
    end_time: float
    duration_seconds: float
    render_profile: str
    content_type: str
    file_size: int | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ClipPage(BaseModel):
    total: int
    offset: int
    limit: int
    clips: list[ClipRead]
