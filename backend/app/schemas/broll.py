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


class BrollSuggestionRead(BaseModel):
    """What visual would help, and when (clip-local seconds)."""

    id: uuid.UUID
    analysis_id: uuid.UUID
    start: float
    end: float
    query: str
    reason: str
    status: str
    # The project's visual assets that likely show it (by name, description and tags),
    # strongest first. Offered to the creator, never placed automatically.
    matches: list[uuid.UUID] = []


class BrollStateRead(BaseModel):
    analysis: BrollAnalysisRead | None
    suggestions: list[BrollSuggestionRead]


class BrollSuggestionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BrollSuggestionStatus
