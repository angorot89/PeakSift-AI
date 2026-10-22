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


class PerformanceOverviewRead(BaseModel):
    access: AnalyticsAccessRead
    videos: list[VideoPerformanceRead]


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
