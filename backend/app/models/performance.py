"""Performance analytics: what happened to a PeakSift short after it was published.

- ``PublishedContent`` links one remote video (provider + remote id) to the PeakSift output that
  produced it — the project, clip, rendered edit, the Auto Edit plan when one was applied, and
  the publish job — and stores an **immutable provenance snapshot**: normalized edit features
  (recipe, layout, captions, hook, visuals, audio, semantic matching, candidate rank) captured
  from the edit's own configuration at publication. Later changes to the project never rewrite
  it; deleting the edit or the plan keeps the content and its provenance (the links become empty).
- ``PerformanceSnapshot`` is one observation: **current counters** (the Data API's live view,
  like and comment counts) or **analytics totals** (the Analytics API's processed figures, which
  run 2–3 days behind, ``provider_data_through``). Every metric is nullable: NULL means the
  provider gave no value; 0 means it reported zero.
- ``PerformanceDailyMetric`` is one processed reporting day of one video, unique per
  ``(content, source, date, metric_version)`` and upserted, so repeated syncs never duplicate a
  day. ``metric_version`` names the provider's metric definitions for that date (YouTube changed
  what a "view" is on 2025-03-31 for Shorts and on 2026-08-27 for every format), so incompatible
  definitions are never compared.
- ``AnalyticsSync`` is one sync job of one content (fenced attempt token, honest status). At most
  one sync per content is active at a time (a partial unique index).

``source`` says where numbers came from: ``youtube``, or ``fake`` — the deterministic provider
for tests and non-production stacks, refused in production and always labelled as simulated.

Analytics belong to the creator: every row hangs off a user and a project; deleting the project
deletes its analytics, and disconnecting YouTube stops future syncs without deleting history.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RemoteStatus(StrEnum):
    ACTIVE = "active"  # the provider still has the video
    REMOTE_MISSING = "remote_missing"  # deleted or no longer visible to the owner
    UNKNOWN = "unknown"  # never checked yet


class DataSource(StrEnum):
    YOUTUBE = "youtube"
    FAKE = "fake"  # deterministic simulation: tests and non-production stacks only


class SnapshotClass(StrEnum):
    COUNTERS = "counters"  # live public counters (Data API)
    ANALYTICS_TOTAL = "analytics_total"  # processed analytics totals (Analytics API), delayed


class SyncStatus(StrEnum):
    QUEUED = "queued"
    SYNCING = "syncing"
    COMPLETED = "completed"
    FAILED = "failed"


class SyncKind(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"  # the creator asked for a refresh
    BACKFILL = "backfill"  # first sync after analytics access was granted


ACTIVE_SYNC_STATUSES = (SyncStatus.QUEUED, SyncStatus.SYNCING)
ERROR_MESSAGE_MAX_LENGTH = 500

_METRICS_NONNEGATIVE = (
    "(views IS NULL OR views >= 0) AND (engaged_views IS NULL OR engaged_views >= 0) "
    "AND (likes IS NULL OR likes >= 0) AND (comments IS NULL OR comments >= 0) "
    "AND (watch_time_seconds IS NULL OR watch_time_seconds >= 0) "
    "AND (average_view_duration_seconds IS NULL OR average_view_duration_seconds >= 0) "
    "AND (average_view_percentage IS NULL OR average_view_percentage >= 0) "
    "AND (subscribers_gained IS NULL OR subscribers_gained >= 0)"
)


class PublishedContent(Base):
    __tablename__ = "published_contents"
    __table_args__ = (
        UniqueConstraint("provider", "remote_video_id", name="uq_published_contents_remote"),
        UniqueConstraint("publish_job_id", name="uq_published_contents_publish_job"),
        CheckConstraint("provider IN ('youtube')", name="ck_published_contents_provider"),
        CheckConstraint(
            "remote_status IN ('active', 'remote_missing', 'unknown')",
            name="ck_published_contents_remote_status",
        ),
        CheckConstraint("length(remote_video_id) > 0", name="ck_published_contents_remote_id"),
        CheckConstraint(
            "jsonb_typeof(provenance) = 'object'", name="ck_published_contents_provenance"
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0",
            name="ck_published_contents_duration",
        ),
        Index("ix_published_contents_next_sync", "next_sync_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # What produced it. The rows may be deleted later; the provenance snapshot stays.
    clip_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="SET NULL")
    )
    edit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clip_edits.id", ondelete="SET NULL")
    )
    auto_edit_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auto_edit_plans.id", ondelete="SET NULL")
    )
    publish_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("publish_jobs.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(16))
    remote_video_id: Mapped[str] = mapped_column(String(64))

    # What the creator published (the reviewed title; never the transcript).
    title: Mapped[str] = mapped_column(String(100))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    privacy: Mapped[str | None] = mapped_column(String(16))
    remote_status: Mapped[str] = mapped_column(String(16), default=RemoteStatus.UNKNOWN)

    # Normalized edit features at publication (see services/performance/provenance.py).
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provenance_version: Mapped[str] = mapped_column(String(32))

    # Sync bookkeeping.
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The last reporting day the provider has fully processed for this video.
    analytics_complete_through: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    snapshots: Mapped[list["PerformanceSnapshot"]] = relationship(
        back_populates="content", cascade="all, delete-orphan", passive_deletes=True
    )
    daily_metrics: Mapped[list["PerformanceDailyMetric"]] = relationship(
        back_populates="content",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PerformanceDailyMetric.date",
    )
    syncs: Mapped[list["AnalyticsSync"]] = relationship(
        back_populates="content", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"PublishedContent(id={self.id!r}, provider={self.provider!r})"


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"
    __table_args__ = (
        CheckConstraint("source IN ('youtube', 'fake')", name="ck_performance_snapshots_source"),
        CheckConstraint(
            "data_class IN ('counters', 'analytics_total')", name="ck_performance_snapshots_class"
        ),
        CheckConstraint(_METRICS_NONNEGATIVE, name="ck_performance_snapshots_nonnegative"),
        Index("ix_performance_snapshots_content_observed", "content_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("published_contents.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(16))
    data_class: Mapped[str] = mapped_column(String(16))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_data_through: Mapped[date | None] = mapped_column(Date)
    metric_version: Mapped[str] = mapped_column(String(32))

    views: Mapped[int | None] = mapped_column(BigInteger)
    engaged_views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    watch_time_seconds: Mapped[float | None] = mapped_column(Float)
    average_view_duration_seconds: Mapped[float | None] = mapped_column(Float)
    average_view_percentage: Mapped[float | None] = mapped_column(Float)
    subscribers_gained: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    content: Mapped[PublishedContent] = relationship(back_populates="snapshots")


class PerformanceDailyMetric(Base):
    __tablename__ = "performance_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "content_id",
            "source",
            "date",
            "metric_version",
            name="uq_performance_daily_metrics_day",
        ),
        CheckConstraint("source IN ('youtube', 'fake')", name="ck_performance_daily_source"),
        CheckConstraint(_METRICS_NONNEGATIVE, name="ck_performance_daily_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Indexed by the day constraint (content first).
    content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("published_contents.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(16))
    date: Mapped[date] = mapped_column(Date)  # the provider's reporting day (Pacific Time)
    metric_version: Mapped[str] = mapped_column(String(32))

    views: Mapped[int | None] = mapped_column(BigInteger)
    engaged_views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    watch_time_seconds: Mapped[float | None] = mapped_column(Float)
    average_view_duration_seconds: Mapped[float | None] = mapped_column(Float)
    average_view_percentage: Mapped[float | None] = mapped_column(Float)
    subscribers_gained: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    content: Mapped[PublishedContent] = relationship(back_populates="daily_metrics")


class AnalyticsSync(Base):
    __tablename__ = "analytics_syncs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'syncing', 'completed', 'failed')",
            name="ck_analytics_syncs_status",
        ),
        CheckConstraint(
            "kind IN ('scheduled', 'manual', 'backfill')", name="ck_analytics_syncs_kind"
        ),
        CheckConstraint("attempt >= 1", name="ck_analytics_syncs_attempt"),
        CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL", name="ck_analytics_syncs_failed"
        ),
        CheckConstraint("days_upserted >= 0", name="ck_analytics_syncs_days"),
        # One active sync per content: overlapping jobs are impossible, not just unlikely.
        Index(
            "uq_analytics_syncs_active",
            "content_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'syncing')"),
        ),
        Index("ix_analytics_syncs_content_created", "content_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("published_contents.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=SyncStatus.QUEUED)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    days_upserted: Mapped[int] = mapped_column(Integer, default=0)
    data_through: Mapped[date | None] = mapped_column(Date)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
    # Attempt-ownership token (fencing), committed before the job is enqueued. Internal.
    celery_task_id: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    content: Mapped[PublishedContent] = relationship(back_populates="syncs")

    def __repr__(self) -> str:
        return f"AnalyticsSync(id={self.id!r}, status={self.status!r})"
