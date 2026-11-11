"""The Shorts library and one Short: what the creator needs, never internals (no storage keys,
task ids, fingerprints, provider payloads or configuration snapshots)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.performance import AnalyticsAccessRead


class ShortProject(BaseModel):
    id: uuid.UUID
    name: str


class ShortSource(BaseModel):
    id: uuid.UUID
    filename: str


class ShortVersion(BaseModel):
    number: int
    count: int


class ShortTemplate(BaseModel):
    """The template version this Short was made with (recorded with it; display only)."""

    id: uuid.UUID | None
    name: str
    version: int | None


class ShortBrand(BaseModel):
    name: str


class ShortPublish(BaseModel):
    state: str
    platform: str | None
    published_at: datetime | None
    uploaded_at: datetime | None
    privacy: str | None
    simulated: bool
    # A link to the video, only when YouTube has a real one (never for simulated uploads).
    video_url: str | None
    job_id: uuid.UUID | None


class ShortPerformance(BaseModel):
    """The latest figures the platform reported; ``None`` is "not reported", never 0."""

    content_id: uuid.UUID
    views: int | None
    likes: int | None
    comments: int | None
    observed_at: datetime | None
    simulated: bool
    analytics_through: date | None


class ShortRead(BaseModel):
    id: uuid.UUID
    kind: str  # short | draft
    status: str
    reason: str | None
    title: str
    edit_id: uuid.UUID | None
    clip_id: uuid.UUID
    project: ShortProject
    source: ShortSource
    duration_seconds: float | None
    preview: str | None  # short | clip | None
    version: ShortVersion | None
    template: ShortTemplate | None
    brand: ShortBrand | None
    auto_edit: bool
    plan_ready: bool
    publish: ShortPublish
    performance: ShortPerformance | None
    created_at: datetime
    updated_at: datetime
    rendered_at: datetime | None


class ShortsLibraryRead(BaseModel):
    shorts: list[ShortRead]
    truncated: bool


class ShortMoment(BaseModel):
    start_time: float
    end_time: float
    rank: int
    category: str


class ShortVersionRead(BaseModel):
    id: uuid.UUID
    number: int
    status: str
    created_at: datetime


class ShortRender(BaseModel):
    error_message: str | None
    file_size: int | None
    progress_percent: int


class ShortDetailRead(ShortRead):
    moment: ShortMoment
    versions: list[ShortVersionRead]
    render: ShortRender
    auto_edit_plan_id: uuid.UUID | None
    # Whether performance can be shown for this creator (and whether it is simulated).
    analytics: AnalyticsAccessRead
