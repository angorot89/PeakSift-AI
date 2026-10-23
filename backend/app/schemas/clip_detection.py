import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderOptionRead(BaseModel):
    """A provider the user may choose, with its allowed models. Never endpoints or keys."""

    name: str
    label: str
    models: list[str]
    default_model: str | None
    configured: bool
    # Live diagnostics, only filled when requested with ?diagnose=true.
    available: bool | None = None
    detail: str | None = None


class StartDetectionRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str | None = Field(default=None, min_length=1, max_length=128)


class DetectionRunRead(BaseModel):
    """Job status. Polling-friendly: no candidates, no task ids, no internals."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    transcription_id: uuid.UUID
    provider: str
    model: str
    status: str
    progress_percent: int
    windows_total: int | None
    windows_done: int
    attempt: int
    candidate_count: int
    is_stale: bool
    # True when the video's current transcript is still the one this run analysed; null
    # while the run is active (not evaluated on every poll).
    transcript_current: bool | None
    config: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class DetectionRunPage(BaseModel):
    total: int
    offset: int
    limit: int
    runs: list[DetectionRunRead]


class CandidateScores(BaseModel):
    hook: int
    entertainment: int
    clarity: int
    payoff: int
    completeness: int


class ClipCandidateRead(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    video_id: uuid.UUID
    rank: int
    start: float
    end: float
    duration: float
    title: str
    hook: str
    rationale: str
    category: str
    transcript_excerpt: str
    overall_score: int
    scores: CandidateScores
    decision: str
    decided_at: datetime | None
    created_at: datetime


class CandidateCounts(BaseModel):
    """How many of the run's candidates each review filter holds."""

    active: int  # everything not dismissed
    top: int  # not dismissed, and rank 1 or a strong editorial score
    saved: int
    dismissed: int


class CandidatePage(BaseModel):
    run_id: uuid.UUID
    total: int
    offset: int
    limit: int
    candidates: list[ClipCandidateRead]
    counts: CandidateCounts
