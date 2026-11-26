"""Scheduled publishing: a job that waits for its time, and the scheduler that releases it.

A scheduled job is an ordinary publish job in the ``scheduled`` status with a ``scheduled_at``.
Nothing about it runs until :func:`release_due` — called by Celery beat every minute — moves it
to ``queued`` and hands it to the same upload pipeline as "publish now". So scheduling adds no
second way to upload: the same checks, the same idempotency, the same retry.

What the creator can rely on:

- A post goes out at its time or within the scheduler's interval after it, never before.
- If the scheduler was down, a post that is late by less than ``publish_schedule_grace_seconds``
  still goes out; an older one is marked *missed* instead of appearing at a time nobody chose.
- If the Short or the account is no longer usable at that moment, the job fails with the
  reason. It is never silently dropped and never uploaded later by surprise.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    ClipEdit,
    ClipEditStatus,
    ConnectionStatus,
    PublishingConnection,
    PublishJob,
    PublishStatus,
)
from app.workers.dispatch import JobQueueUnavailable, new_task_id

logger = logging.getLogger(__name__)

MIN_LEAD = timedelta(minutes=2)  # anything sooner is "publish now"
MAX_AHEAD = timedelta(days=366)
RELEASE_BATCH = 50


class ScheduleError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_time(when: datetime, now: datetime | None = None) -> datetime:
    """A usable publish time in UTC, or :class:`ScheduleError`."""
    now = now or datetime.now(UTC)
    if when.tzinfo is None:
        raise ScheduleError("Send the time with its time zone")
    when = when.astimezone(UTC).replace(microsecond=0)
    if when < now + MIN_LEAD:
        raise ScheduleError("Pick a time at least a few minutes from now, or publish now")
    if when > now + MAX_AHEAD:
        raise ScheduleError("Pick a time within the next year")
    return when


def _fail(job: PublishJob, code: str, message: str, now: datetime) -> None:
    job.status = PublishStatus.FAILED
    job.error_code = code
    job.error_message = message
    job.completed_at = now


def release_due(
    db: Session,
    settings: Settings,
    enqueue: Callable[..., object],
    now: datetime | None = None,
) -> list[uuid.UUID]:
    """Move every due job to ``queued`` and enqueue it. Returns the ids released.

    Rows are locked ``SKIP LOCKED`` so two schedulers never release the same job, and the
    fencing token is committed before the job is handed to the broker.
    """
    now = now or datetime.now(UTC)
    grace = timedelta(seconds=settings.publish_schedule_grace_seconds)
    due = db.scalars(
        select(PublishJob)
        .where(PublishJob.status == PublishStatus.SCHEDULED, PublishJob.scheduled_at <= now)
        .order_by(PublishJob.scheduled_at)
        .limit(RELEASE_BATCH)
        .with_for_update(skip_locked=True)
    ).all()
    ready: list[PublishJob] = []
    for job in due:
        edit = db.get(ClipEdit, job.edit_id)
        connection = db.get(PublishingConnection, job.connection_id) if job.connection_id else None
        if now - job.scheduled_at > grace:
            _fail(
                job,
                "schedule_missed",
                "PeakSift was not running at the scheduled time. Publish it now or pick a "
                "new time.",
                now,
            )
        elif edit is None or edit.status != ClipEditStatus.READY or not edit.storage_key:
            _fail(
                job, "edit_not_ready", "The Short was no longer ready at the scheduled time.", now
            )
        elif connection is None or connection.status != ConnectionStatus.CONNECTED:
            _fail(
                job,
                "needs_reconnect",
                "Your YouTube account was not connected at the scheduled time. Reconnect it, "
                "then publish this Short.",
                now,
            )
        else:
            job.status = PublishStatus.QUEUED
            job.celery_task_id = new_task_id()
            ready.append(job)
    db.commit()

    released: list[uuid.UUID] = []
    for job in ready:
        try:
            enqueue(job.id, task_id=job.celery_task_id)
            released.append(job.id)
        except JobQueueUnavailable:
            # Put it back: the next tick tries again (still inside the grace period).
            job.status = PublishStatus.SCHEDULED
            job.celery_task_id = None
            db.commit()
            logger.warning("Scheduled publish %s could not be queued; will retry", job.id)
    if due:
        logger.info("Scheduled publishing: %d due, %d released", len(due), len(released))
    return released


def scheduled_for_edit(
    db: Session, user_id: uuid.UUID, edit_id: uuid.UUID, provider: str = "youtube"
) -> PublishJob | None:
    """The Short's post that is still waiting on this platform (one per platform)."""
    return db.scalar(
        select(PublishJob).where(
            PublishJob.user_id == user_id,
            PublishJob.edit_id == edit_id,
            PublishJob.provider == provider,
            PublishJob.status == PublishStatus.SCHEDULED,
        )
    )
