"""Syncing one published video's metrics: requesting it, running it, and when to sync next.

Every ``AnalyticsSync`` row is one attempt and stays as history. These helpers are the only way
the API, the scheduler and the job change them.

- **Requesting** (``request_sync``): at most one queued or syncing sync per video — enforced by
  a partial unique index, not just checked. A sync whose worker stopped reporting is recorded as
  ``stalled`` and replaced. The task id is committed on the row *before* the job is enqueued
  (the fencing token). A creator's refresh is refused for a short cooldown after the last sync.
- **Running** (``run_sync``): only the sync id travels through the broker. With the creator's
  analytics grant (the stored, encrypted refresh token; checked again here), the job reads the
  video's live counters (one snapshot) and its processed daily analytics from the reporting day
  of publication — or, after the first sync, from a few days before the last settled day, since
  recent days are still being revised — and upserts one row per day and view definition.
  Snapshots and rows record the provider's name as their source, so simulated data is always
  labelled.
- **Missing videos:** a video the provider no longer returns is marked ``remote_missing``; its
  history is kept and it is no longer scheduled (a creator's refresh checks again).
- **Ownership:** every commit re-reads the token and status, so a stalled worker whose sync was
  replaced never writes again; a video deleted mid-run stops the job.
- **Failures** record a safe code and message (never Google's words, tokens or paths) and set
  the next attempt with a backoff; a refused grant marks the connection for reconnecting, as
  publishing does.

``next_sync_at`` follows the video's age: frequent while short-form views are moving, rarer
later, and never after 180 days (a creator's refresh still works).
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from app.core.config import Settings, get_settings
from app.models import (
    ACTIVE_SYNC_STATUSES,
    AnalyticsSync,
    ConnectionStatus,
    PerformanceDailyMetric,
    PerformanceSnapshot,
    PublishedContent,
    PublishingConnection,
    RemoteStatus,
    SnapshotClass,
    SyncKind,
    SyncStatus,
)
from app.models.performance import ERROR_MESSAGE_MAX_LENGTH
from app.services.performance.content import link_existing
from app.services.performance.factory import get_performance_provider
from app.services.performance.metrics import METRICS, metric_version, reporting_today
from app.services.performance.provider import (
    PerformanceErrorCode,
    PerformanceProvider,
    PerformanceProviderError,
)
from app.services.publishing import connections
from app.services.publishing.tokens import TokenCipher, TokenDecryptionError
from app.services.publishing.youtube_oauth import ANALYTICS_SCOPE, READONLY_SCOPE

logger = logging.getLogger(__name__)

# YouTube's processed analytics arrive 2–3 days late and recent days may still change: days
# older than this are treated as settled, and each sync re-reads a few days before that.
SETTLED_AFTER_DAYS = 3
REVISION_DAYS = 3
# Scheduled syncs stop after this age; one sync never asks for more than this many days.
SCHEDULE_UNTIL = timedelta(days=180)
MAX_RANGE_DAYS = 400
BACKOFF_MAX = timedelta(hours=24)
# How many videos a newly granted creator's backfill starts at once (the scheduler does the rest).
BACKFILL_START_LIMIT = 20

MESSAGES = {
    "stalled": "The metrics refresh stopped responding; it will run again",
    "not_connected": "Connect YouTube to see metrics",
    "reconnect_required": "YouTube needs you to reconnect your account",
    "analytics_not_connected": "Analytics access is not connected",
    "token_unreadable": "YouTube needs you to reconnect your account",
    "queue_unavailable": "The metrics refresh could not start; it will run again",
    "time_limit": "The metrics refresh took too long; it will run again",
    "internal_error": "Unexpected error while refreshing metrics; it will run again",
}

# Failures worth retrying on their own later (with a backoff); others wait for the creator.
RETRY_LATER = {
    PerformanceErrorCode.QUOTA_EXCEEDED, PerformanceErrorCode.RATE_LIMITED,
    PerformanceErrorCode.NETWORK_ERROR, PerformanceErrorCode.PROVIDER_ERROR,
    PerformanceErrorCode.INVALID_RESPONSE, PerformanceErrorCode.API_NOT_ENABLED,
    "stalled", "queue_unavailable", "time_limit", "internal_error",
}  # fmt: skip


class SyncSuperseded(Exception):
    """A newer attempt replaced this sync (or the video is gone); stop without writing."""


class SyncFailure(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message or MESSAGES[code]


class RefreshTooSoon(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("refresh too soon")
        self.retry_after_seconds = retry_after_seconds


def now() -> datetime:
    return datetime.now(UTC)


def new_task_id() -> str:
    return str(uuid.uuid4())


# --- when to sync ------------------------------------------------------------------------------


def next_sync_after(published_at: datetime, at: datetime) -> datetime | None:
    """The next scheduled sync for a video of this age, or None once it is old enough."""
    age = at - published_at
    if age >= SCHEDULE_UNTIL:
        return None
    if age < timedelta(days=2):
        gap = timedelta(hours=6)
    elif age < timedelta(days=7):
        gap = timedelta(hours=12)
    elif age < timedelta(days=30):
        gap = timedelta(days=1)
    elif age < timedelta(days=90):
        gap = timedelta(days=3)
    else:
        gap = timedelta(days=7)
    return at + gap


def backoff(attempt: int) -> timedelta:
    return min(BACKOFF_MAX, timedelta(hours=2 ** max(0, attempt - 1)))


def has_analytics_grant(connection: PublishingConnection | None) -> bool:
    if connection is None or connection.status != ConnectionStatus.CONNECTED:
        return False
    granted = set(connection.scopes.split())
    return READONLY_SCOPE in granted and ANALYTICS_SCOPE in granted


# --- requesting --------------------------------------------------------------------------------


def active_sync(db: Session, content: PublishedContent) -> AnalyticsSync | None:
    return db.scalar(
        select(AnalyticsSync).where(
            AnalyticsSync.content_id == content.id,
            AnalyticsSync.status.in_(ACTIVE_SYNC_STATUSES),
        )
    )


def last_sync(db: Session, content: PublishedContent) -> AnalyticsSync | None:
    return db.scalar(
        select(AnalyticsSync)
        .where(AnalyticsSync.content_id == content.id)
        .order_by(AnalyticsSync.created_at.desc(), AnalyticsSync.id.desc())
        .limit(1)
    )


def is_stale(sync: AnalyticsSync, settings: Settings, *, at: datetime | None = None) -> bool:
    if sync.status not in ACTIVE_SYNC_STATUSES:
        return False
    last = sync.heartbeat_at or sync.started_at or sync.created_at
    return ((at or now()) - last).total_seconds() > settings.performance_sync_stale_after_seconds


def request_sync(
    db: Session, content: PublishedContent, kind: SyncKind, settings: Settings
) -> AnalyticsSync | None:
    """A new queued sync with its task id committed, or None when one is already running."""
    running = active_sync(db, content)
    if running is not None:
        if not is_stale(running, settings):
            return None
        running.status = SyncStatus.FAILED
        running.error_code, running.error_message = "stalled", MESSAGES["stalled"]
        running.completed_at = now()
        db.commit()
    previous = last_sync(db, content)
    attempt = previous.attempt + 1 if previous and previous.status == SyncStatus.FAILED else 1
    sync = AnalyticsSync(
        content_id=content.id, kind=kind, status=SyncStatus.QUEUED, attempt=attempt,
        celery_task_id=new_task_id(), created_at=now(),  # orders attempts, even in one transaction
    )  # fmt: skip
    db.add(sync)
    try:
        db.commit()
    except IntegrityError:  # another request started one at the same moment
        db.rollback()
        return None
    return sync


def request_manual_sync(
    db: Session, content: PublishedContent, settings: Settings, *, at: datetime | None = None
) -> AnalyticsSync | None:
    """A creator's refresh: refused (``RefreshTooSoon``) right after a sync."""
    at = at or now()
    cooldown = timedelta(seconds=settings.performance_manual_cooldown_seconds)
    if content.last_synced_at is not None and at - content.last_synced_at < cooldown:
        wait = cooldown - (at - content.last_synced_at)
        raise RefreshTooSoon(max(1, int(wait.total_seconds())))
    return request_sync(db, content, SyncKind.MANUAL, settings)


def mark_enqueue_failed(db: Session, sync: AnalyticsSync) -> None:
    db.rollback()
    sync.status = SyncStatus.FAILED
    sync.error_code, sync.error_message = "queue_unavailable", MESSAGES["queue_unavailable"]
    sync.completed_at = now()
    db.commit()


def due_contents(db: Session, settings: Settings, at: datetime) -> list[PublishedContent]:
    """Videos whose next sync is due, of creators who granted analytics access."""
    rows = db.scalars(
        select(PublishedContent)
        .join(PublishingConnection, PublishingConnection.user_id == PublishedContent.user_id)
        .where(
            PublishedContent.next_sync_at.is_not(None),
            PublishedContent.next_sync_at <= at,
            PublishedContent.remote_status != RemoteStatus.REMOTE_MISSING,
            PublishingConnection.status == ConnectionStatus.CONNECTED,
            PublishingConnection.scopes.contains(ANALYTICS_SCOPE),
            PublishingConnection.scopes.contains(READONLY_SCOPE),
            ~select(AnalyticsSync.id)
            .where(
                AnalyticsSync.content_id == PublishedContent.id,
                AnalyticsSync.status.in_(ACTIVE_SYNC_STATUSES),
            )
            .exists(),
        )
        .order_by(PublishedContent.next_sync_at, PublishedContent.id)
        .limit(settings.performance_schedule_batch)
    )
    return list(rows)


def mark_backfill_due(db: Session, user_id: uuid.UUID, *, at: datetime | None = None) -> int:
    """After a creator grants analytics access: link uploads PeakSift made before V1.4 (only
    those — never other videos on the channel) and make all their videos due now."""
    at = at or now()
    link_existing(db, user_id)
    contents = db.scalars(
        select(PublishedContent).where(
            PublishedContent.user_id == user_id,
            PublishedContent.remote_status != RemoteStatus.REMOTE_MISSING,
        )
    ).all()
    for content in contents:
        content.next_sync_at = at
    db.commit()
    return len(contents)


# --- ownership ---------------------------------------------------------------------------------


def still_owner(db: Session, sync_id: uuid.UUID, task_id: str | None) -> bool:
    with db.no_autoflush:
        row = db.execute(
            select(AnalyticsSync.celery_task_id, AnalyticsSync.status).where(
                AnalyticsSync.id == sync_id
            )
        ).first()
    if row is None or row.status != SyncStatus.SYNCING:
        return False
    return task_id is None or row.celery_task_id == task_id


def ensure_still_owner(db: Session, sync_id: uuid.UUID, task_id: str | None) -> None:
    if not still_owner(db, sync_id, task_id):
        db.rollback()
        raise SyncSuperseded()


def claim(sync: AnalyticsSync, db: Session, task_id: str | None) -> bool:
    if task_id and sync.celery_task_id != task_id:
        logger.info("Analytics sync %s belongs to another attempt; ignoring", sync.id)
        return False
    if sync.status != SyncStatus.QUEUED:
        logger.info("Analytics sync %s is %s; ignoring duplicate task", sync.id, sync.status)
        return False
    sync.status = SyncStatus.SYNCING
    sync.started_at = sync.heartbeat_at = now()
    db.commit()
    return True


def fail(
    db: Session, sync: AnalyticsSync, error: SyncFailure, *, task_id: str | None, at: datetime
) -> None:
    db.rollback()
    sync_id = sync.id
    if not still_owner(db, sync_id, task_id):
        logger.info("Analytics sync %s failed (%s) after being replaced; ignoring", sync_id,
                    error.code)  # fmt: skip
        return
    sync.status = SyncStatus.FAILED
    sync.error_code = error.code[:64]
    sync.error_message = error.message[:ERROR_MESSAGE_MAX_LENGTH]
    sync.completed_at = sync.heartbeat_at = now()
    content = sync.content
    if error.code in RETRY_LATER:
        content.next_sync_at = at + backoff(sync.attempt)
    else:  # needs the creator (or operator): the next grant or refresh starts again
        content.next_sync_at = None
    db.commit()
    logger.warning("Analytics sync %s failed: %s", sync_id, error.code)


# --- the work ----------------------------------------------------------------------------------


def _range(content: PublishedContent, today: date) -> tuple[date, date] | None:
    published = reporting_today(content.published_at)
    start = published
    if content.analytics_complete_through is not None:
        start = max(published, content.analytics_complete_through - timedelta(REVISION_DAYS))
    start = max(start, today - timedelta(MAX_RANGE_DAYS))
    return (start, today) if start <= today else None


def _upsert_days(db: Session, content: PublishedContent, source: str, days) -> None:
    if not days:
        return
    rows = [
        {"content_id": content.id, "source": source, "date": day.day,
         "metric_version": metric_version(day.day),
         **{name: getattr(day, name) for name in METRICS}}
        for day in days
    ]  # fmt: skip
    statement = insert(PerformanceDailyMetric).values(rows)
    db.execute(
        statement.on_conflict_do_update(
            constraint="uq_performance_daily_metrics_day",
            set_={
                **{name: getattr(statement.excluded, name) for name in METRICS},
                "updated_at": now(),
            },
        )
    )


def _execute(
    sync: AnalyticsSync,
    db: Session,
    settings: Settings,
    provider: PerformanceProvider,
    task_id: str | None,
    at: datetime,
) -> None:
    content = sync.content
    connection = connections.get_connection(db, content.user_id)
    if connection is None:
        raise SyncFailure("not_connected")
    if connection.status != ConnectionStatus.CONNECTED:
        raise SyncFailure("reconnect_required")
    if not has_analytics_grant(connection):
        raise SyncFailure("analytics_not_connected")
    try:
        token = connections.refresh_token_of(db, TokenCipher.from_settings(settings), connection)
    except TokenDecryptionError:
        raise SyncFailure("token_unreadable") from None
    auth = provider.authorize(token)
    del token

    today = reporting_today(at)
    counters = provider.video_counters(auth, [content.remote_video_id])
    ensure_still_owner(db, sync.id, task_id)
    sync.heartbeat_at = now()
    found = counters.get(content.remote_video_id)
    if found is None:
        content.remote_status = RemoteStatus.REMOTE_MISSING
        content.last_synced_at = at
        content.next_sync_at = None
        _complete(db, sync, task_id, days=0, data_through=None)
        logger.info("Published content %s is no longer on %s", content.id, content.provider)
        return
    content.remote_status = RemoteStatus.ACTIVE
    content.privacy = found.privacy or content.privacy
    db.add(
        PerformanceSnapshot(
            content_id=content.id, source=provider.name, data_class=SnapshotClass.COUNTERS,
            observed_at=at, provider_data_through=None, metric_version=metric_version(today),
            views=found.views, likes=found.likes, comments=found.comments,
        )
    )  # fmt: skip
    db.commit()

    window = _range(content, today)
    days = provider.daily_metrics(auth, content.remote_video_id, *window) if window else []
    ensure_still_owner(db, sync.id, task_id)
    _upsert_days(db, content, provider.name, days)
    data_through = max((day.day for day in days), default=None)
    if data_through is not None:
        settled = min(data_through, today - timedelta(SETTLED_AFTER_DAYS))
        if (
            content.analytics_complete_through is None
            or settled > content.analytics_complete_through
        ):
            content.analytics_complete_through = settled
    content.last_synced_at = at
    content.next_sync_at = next_sync_after(content.published_at, at)
    _complete(db, sync, task_id, days=len(days), data_through=data_through)


def _complete(db, sync, task_id, *, days: int, data_through: date | None) -> None:
    ensure_still_owner(db, sync.id, task_id)
    sync.status = SyncStatus.COMPLETED
    sync.days_upserted = days
    sync.data_through = data_through
    sync.completed_at = sync.heartbeat_at = now()
    db.commit()


def run_sync(
    sync_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    provider: PerformanceProvider | None = None,
    task_id: str | None = None,
    at: datetime | None = None,
) -> AnalyticsSync | None:
    """Run one ``AnalyticsSync``. Problems are recorded, never raised."""
    settings = settings or get_settings()
    sync = db.get(AnalyticsSync, sync_id)
    if sync is None:
        logger.info("Analytics sync %s no longer exists; nothing to do", sync_id)
        return None
    if not claim(sync, db, task_id):
        return sync
    at = at or now()

    def record(error: SyncFailure) -> None:
        try:
            fail(db, sync, error, task_id=task_id, at=at)
        except Exception:
            logger.exception("Could not record the failure of analytics sync %s", sync_id)
            db.rollback()

    try:
        provider = provider or get_performance_provider(settings)
        _execute(sync, db, settings, provider, task_id, at)
    except (SyncSuperseded, ObjectDeletedError):
        db.rollback()
        logger.info("Analytics sync %s was replaced or removed; stopping", sync_id)
    except SyncFailure as error:
        record(error)
    except PerformanceProviderError as error:
        if error.code == PerformanceErrorCode.AUTHENTICATION_REQUIRED:
            connection = connections.get_connection(db, sync.content.user_id)
            if connection is not None:
                connections.mark_needs_reconnect(db, connection)
        record(SyncFailure(error.code, error.message))
    except SoftTimeLimitExceeded:
        record(SyncFailure("time_limit"))
    except Exception:
        logger.exception("Unexpected error in analytics sync %s", sync_id)
        record(SyncFailure("internal_error"))
    return sync
