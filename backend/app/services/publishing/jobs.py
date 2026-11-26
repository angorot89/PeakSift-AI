"""Creating publish jobs: only a READY edit, only through a working connection, never twice.

``request_publish`` refuses anything but a ready edit and a ``connected`` account, then
either creates a ``queued`` job (with its fencing token already set, so it can be enqueued
right after the commit), or a ``scheduled`` one when a time was given, or returns the job
the same request created before — the same edit, connection and metadata are never uploaded
twice, even when two requests race.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ClipEdit,
    ClipEditStatus,
    ConnectionStatus,
    PublishingConnection,
    PublishJob,
    PublishStatus,
)
from app.services.publishing.metadata import DEFAULT_CATEGORY_ID, PublishMetadata, fingerprint


class PublishRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def request_publish(
    db: Session,
    *,
    user_id: uuid.UUID,
    edit: ClipEdit,
    connection: PublishingConnection | None,
    metadata: PublishMetadata,
    task_id: str,
    scheduled_at: datetime | None = None,
    options: dict | None = None,
    platform: str = "YouTube",
) -> tuple[PublishJob, bool]:
    """``(job, created)``. Raises :class:`PublishRefused` for an unready edit or account."""
    if edit.status != ClipEditStatus.READY or not edit.storage_key:
        raise PublishRefused("edit_not_ready", "Render the short before publishing it")
    if connection is None:
        raise PublishRefused("not_connected", f"Connect a {platform} account first")
    if connection.status != ConnectionStatus.CONNECTED:
        raise PublishRefused("needs_reconnect", f"Reconnect your {platform} account to publish")

    options = dict(options or {})
    key = fingerprint(
        connection_id=connection.id, edit_id=edit.id, metadata=metadata, options=options
    )
    existing = _by_fingerprint(db, user_id, key)
    if existing is not None:
        return existing, False
    job = PublishJob(
        user_id=user_id,
        edit_id=edit.id,
        connection_id=connection.id,
        provider=connection.provider,
        title=metadata.title,
        description=metadata.description,
        tags=list(metadata.tags),
        privacy=metadata.privacy.value,
        made_for_kids=metadata.made_for_kids,
        category_id=DEFAULT_CATEGORY_ID,
        options=options,
        fingerprint=key,
        # A scheduled job waits; the scheduler gives it its token when it releases it.
        status=PublishStatus.SCHEDULED if scheduled_at else PublishStatus.QUEUED,
        scheduled_at=scheduled_at,
        progress_percent=0,
        attempt=1,
        bytes_uploaded=0,
        celery_task_id=None if scheduled_at else task_id,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:  # the same request, sent concurrently, won the constraint
        db.rollback()
        winner = _by_fingerprint(db, user_id, key)
        if winner is None:
            raise
        return winner, False
    return job, True


def _by_fingerprint(db: Session, user_id: uuid.UUID, key: str) -> PublishJob | None:
    return db.scalar(
        select(PublishJob).where(PublishJob.user_id == user_id, PublishJob.fingerprint == key)
    )
