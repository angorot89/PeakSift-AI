"""Performance analytics as the creator sees it: observed figures, never predictions, never
tokens, task ids or provider payloads. ``None`` means "not reported" — it is never 0."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class AnalyticsAccessRead(BaseModel):
    # The server offers analytics (operator setting).
    enabled: bool
    # A YouTube connection exists, and its status ("connected" / "needs_reconnect").
    connected: bool
    connection_status: str | None
    # The creator granted the read-only analytics upgrade.
    analytics_access: bool
    # Metrics come from the deterministic simulation (non-production stacks only).
    simulated: bool


class SyncRead(BaseModel):
    kind: str
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class WindowRead(BaseModel):
    """One early window in reporting days from publication (day_1 ≈ 24 h, day_3 ≈ 72 h,
    day_7 ≈ a week). Figures only when the window is complete."""

    key: str
    days_expected: int
    days_reported: int
    status: str  # complete | open | incomplete
    engaged_views: int | None
    views: int | None
    average_view_percentage: float | None
    watch_time_seconds: float | None
    likes: int | None
    comments: int | None
    subscribers_gained: int | None


class PositionRead(BaseModel):
    """This short against the creator's own median (the short itself left out)."""

    metric: str
    window: str
    value: float
    median: float
    ratio: float | None
    label: str  # above | near | below


class BaselineRead(BaseModel):
    """The creator's own median over their comparable shorts; never other creators'."""

    metric: str
    window: str
    sample_size: int
    minimum_sample: int
    median: float | None
    reliable: bool


class VideoPerformanceRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    edit_id: uuid.UUID | None
    title: str
    published_at: datetime
    duration_seconds: float | None
    privacy: str | None
    remote_status: str
    # Where the figures came from ("youtube" or "fake"), None before the first sync.
    source: str | None
    simulated: bool
    video_url: str | None
    views: int | None
    likes: int | None
    comments: int | None
    counters_observed_at: datetime | None
    engaged_views: int | None
    average_view_percentage: float | None
    processed_through: date | None
    processed_days: int
    last_synced_at: datetime | None
    next_sync_at: datetime | None
    latest_sync: SyncRead | None
    # The recipe the short was made with ("manual" for hand-made edits).
    recipe: str | None
    windows: list[WindowRead] = []
    positions: list[PositionRead] = []


class PerformanceOverviewRead(BaseModel):
    access: AnalyticsAccessRead
    videos: list[VideoPerformanceRead]
    # Medians among shorts with a complete first week of the current source.
    baselines: list[BaselineRead]


class DailyMetricRead(BaseModel):
    date: date
    metric_version: str
    views: int | None
    engaged_views: int | None
    likes: int | None
    comments: int | None
    watch_time_seconds: float | None
    average_view_duration_seconds: float | None
    average_view_percentage: float | None
    subscribers_gained: int | None


class SnapshotRead(BaseModel):
    observed_at: datetime
    views: int | None
    likes: int | None
    comments: int | None


class VideoPerformanceDetailRead(VideoPerformanceRead):
    # How the short was made: normalized features recorded at publish time (no text, no ids).
    provenance: dict
    daily: list[DailyMetricRead]
    snapshots: list[SnapshotRead]
    syncs: list[SyncRead]


class EvidenceShortRead(BaseModel):
    id: uuid.UUID
    title: str


class InsightRead(BaseModel):
    """One observed pattern among the creator's own shorts: never a cause or a prediction."""

    id: uuid.UUID
    rank: int
    feature: str
    value: str
    metric: str
    window: str
    direction: str  # higher | lower
    group_size: int
    comparison_size: int
    group_median: float
    comparison_median: float
    ratio: float | None
    consistency: float
    confidence: str  # limited | moderate
    statement: str
    dismissed: bool
    group: list[EvidenceShortRead]
    comparison: list[EvidenceShortRead]


class InsightsRead(BaseModel):
    # ready: computed (possibly with no pattern); insufficient: too few comparable shorts.
    status: str
    source: str
    simulated: bool
    engine_version: str
    computed_at: datetime
    sample_size: int
    minimum_sample: int
    minimum_group: int
    insights: list[InsightRead]


class CollectedDataDeletedRead(BaseModel):
    snapshots: int
    days: int
    syncs: int
    insight_sets: int
