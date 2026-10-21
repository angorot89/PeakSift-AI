"""B-roll responses. Never prompts, raw model output, scores, provider internals, task ids,
fingerprints or configuration snapshots."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from app.models.broll import BrollSuggestionStatus


class BrollStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Deliberately ask again once the current suggestions are finished (a new generation).
    regenerate: StrictBool = False


class BrollAnalysisRead(BaseModel):
    id: uuid.UUID
    clip_id: uuid.UUID
    status: str
    progress_percent: int
    attempt: int
    is_stale: bool
    generation: int
    # How the suggestions were made: a local language model, or names found in the
    # transcript (configured that way, or because the model could not answer).
    method: Literal["local_ai", "keyword", "keyword_fallback"]
    suggestion_count: int | None
    rejected_count: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BrollMatchRead(BaseModel):
    """One offered asset: a strength tier and the signal — never a score or a percentage.
    Only strong matches may be placed automatically (Auto Edit); possible ones are offered."""

    asset_id: uuid.UUID
    strength: str  # strong / possible
    method: str  # visual / metadata / visual_and_metadata
    best_frame_time: float | None = None  # videos matched by what they show: the best scene


class BrollSuggestionRead(BaseModel):
    """What visual would help, and when (clip-local seconds)."""

    id: uuid.UUID
    analysis_id: uuid.UUID
    start: float
    end: float
    query: str
    reason: str
    status: str
    # The project's visual assets that likely show it, strongest first (at most three):
    # by what they show and by their name, description and tags. Offered to the creator.
    matches: list[uuid.UUID] = []
    match_details: list[BrollMatchRead] = []


class BrollStateRead(BaseModel):
    analysis: BrollAnalysisRead | None
    suggestions: list[BrollSuggestionRead]


class BrollSuggestionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BrollSuggestionStatus
