"""Workspace summaries for Home and the project overview: facts only, no internals (no
storage keys, task ids, providers or fingerprints)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class SourceSummary(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    duration_seconds: float | None


class TranscriptSummary(BaseModel):
    status: str
    progress_percent: int


class CandidateSummary(BaseModel):
    id: uuid.UUID
    rank: int
    title: str
    start_time: float
    end_time: float
    duration_seconds: float
    category: str
    overall_score: int


class DetectionSummary(BaseModel):
    run_id: uuid.UUID
    status: str
    candidates: int
    undecided: int
    saved: int
    dismissed: int
    top: list[CandidateSummary]


class ClipsSummary(BaseModel):
    total: int
    ready: int
    working: int
    failed: int
    latest_ready_id: uuid.UUID | None


class ShortSummary(BaseModel):
    edit_id: uuid.UUID
    clip_id: uuid.UUID
    clip_title: str
    status: str
    # What tells two versions of one clip apart (never configuration internals).
    layout: str
    captions_enabled: bool
    caption_style: str | None
    duration_seconds: float | None
    # YouTube confirmed the upload (a publish job reached "published"); never an upload in flight.
    published: bool = False
    created_at: datetime
    updated_at: datetime


class ShortsSummary(BaseModel):
    total: int
    ready: int
    working: int
    failed: int
    recent: list[ShortSummary]


class PlanRef(BaseModel):
    plan_id: uuid.UUID
    clip_id: uuid.UUID
    recipe: str


class PlansSummary(BaseModel):
    ready: int
    latest_ready: PlanRef | None


class PublishedSummary(BaseModel):
    uploads: int
    working: int
    failed: int
    # Published shorts of this project with processed YouTube analytics.
    with_analytics: int
    last_synced_at: datetime | None


class NextActionRead(BaseModel):
    """The project's next best step (``services/next_action.py``): one deterministic rule set
    shared by Home, the Overview and the Copilot."""

    key: str
    title: str
    description: str
    cta: str | None
    href: str
    tone: str  # attention | action | waiting | done


class ContinueItemRead(NextActionRead):
    project_id: uuid.UUID
    project_name: str


class ProjectSummaryRead(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_activity_at: datetime
    source: SourceSummary | None
    transcript: TranscriptSummary | None
    detection: DetectionSummary | None
    clips: ClipsSummary
    shorts: ShortsSummary
    plans: PlansSummary
    published: PublishedSummary
    next_action: NextActionRead


class HomeShortRead(ShortSummary):
    project_id: uuid.UUID
    project_name: str


class HomeRead(BaseModel):
    projects: list[ProjectSummaryRead]
    project_count: int
    recent_shorts: list[HomeShortRead]
    # Home's *Continue working*: each project's next step, problems first.
    continue_items: list[ContinueItemRead]
