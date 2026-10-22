"""Starting metric syncs: from the scheduler, a creator's refresh, and a new analytics grant.

``start_sync`` requests a sync (``sync.request_sync``: one active per video, fenced) and
enqueues it. It never fails the caller because of the broker: an unreachable queue is recorded
on the sync as a retryable failure.

``schedule_due`` is what Celery beat (and ``python -m app.cli.performance sync-due``) runs:
a bounded batch of due videos of creators who granted analytics access. ``start_backfill``
runs after a grant: PeakSift's own earlier uploads are linked and synced (a first batch now,
the rest by the scheduler). Nothing here ever reads other videos on the creator's channel.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AnalyticsSync, PublishedContent, SyncKind
from app.services.performance.sync import (
    BACKFILL_START_LIMIT,
    due_contents,
    mark_backfill_due,
    mark_enqueue_failed,
    now,
    request_manual_sync,
    request_sync,
)

logger = logging.getLogger(__name__)


def _enqueue(db: Session, sync: AnalyticsSync) -> None:
    from app.workers.dispatch import JobQueueUnavailable, enqueue_performance_sync

    try:
        enqueue_performance_sync(sync.id, task_id=sync.celery_task_id)
    except JobQueueUnavailable:
        logger.warning("Analytics sync %s could not be enqueued (broker unavailable)", sync.id)
        mark_enqueue_failed(db, sync)


def start_sync(
    db: Session, content: PublishedContent, kind: SyncKind, settings: Settings
) -> AnalyticsSync | None:
    sync = request_sync(db, content, kind, settings)
    if sync is not None:
        _enqueue(db, sync)
    return sync


def start_manual_sync(
    db: Session, content: PublishedContent, settings: Settings
) -> AnalyticsSync | None:
    """A creator's refresh. Raises ``RefreshTooSoon`` during the cooldown."""
    sync = request_manual_sync(db, content, settings)
    if sync is not None:
        _enqueue(db, sync)
    return sync


def schedule_due(db: Session, settings: Settings, *, at: datetime | None = None) -> int:
    """Start syncs for due videos (bounded). Returns how many were started."""
    if not settings.youtube_analytics_enabled:
        return 0
    started = 0
    for content in due_contents(db, settings, at or now()):
        if start_sync(db, content, SyncKind.SCHEDULED, settings) is not None:
            started += 1
    if started:
        logger.info("Started %d scheduled analytics syncs", started)
    return started


def start_backfill(db: Session, user_id: uuid.UUID, settings: Settings) -> int:
    """After a creator granted analytics: link and sync PeakSift's earlier uploads."""
    if not settings.youtube_analytics_enabled:
        return 0
    mark_backfill_due(db, user_id)
    contents = db.scalars(
        select(PublishedContent)
        .where(PublishedContent.user_id == user_id, PublishedContent.next_sync_at.is_not(None))
        .order_by(PublishedContent.published_at.desc())
        .limit(BACKFILL_START_LIMIT)
    ).all()
    started = sum(
        start_sync(db, content, SyncKind.BACKFILL, settings) is not None for content in contents
    )
    logger.info("Started %d analytics backfill syncs", started)
    return started


def start_backfill_quietly(db: Session, user_id: uuid.UUID, settings: Settings) -> None:
    """For the OAuth callback: the grant is saved whatever happens here."""
    try:
        start_backfill(db, user_id, settings)
    except Exception:
        logger.exception("Could not start the analytics backfill")
        db.rollback()
