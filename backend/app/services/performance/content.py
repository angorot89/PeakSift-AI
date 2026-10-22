"""Linking a published remote video to the PeakSift output that produced it.

The link is made from the publish job the moment the provider returns a video id (never by
matching titles): the job names the rendered edit; the edit names its clip, video and project;
an Auto Edit plan whose applied edit is this edit is recorded too. The provenance snapshot is
built then, from those immutable rows (``provenance.build_provenance``).

Linking is best effort and idempotent: a publish never fails because of it, one remote video is
one ``PublishedContent`` (unique per provider + remote id, and per publish job), and jobs that
were uploaded before V1.4 are linked later by ``link_existing``.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AutoEditPlan,
    AutoEditStatus,
    ClipEdit,
    PublishedContent,
    PublishJob,
    RemoteStatus,
)
from app.services.performance.provenance import PROVENANCE_VERSION, build_provenance

logger = logging.getLogger(__name__)

FIRST_SYNC_AFTER = timedelta(hours=6)


def content_for_job(db: Session, job: PublishJob) -> PublishedContent | None:
    return db.scalar(select(PublishedContent).where(PublishedContent.publish_job_id == job.id))


def _applied_plan(db: Session, edit: ClipEdit) -> AutoEditPlan | None:
    return db.scalar(
        select(AutoEditPlan)
        .where(
            AutoEditPlan.clip_edit_id == edit.id,
            AutoEditPlan.status == AutoEditStatus.APPLIED,
        )
        .order_by(AutoEditPlan.applied_at.desc())
        .limit(1)
    )


def link_published_content(db: Session, job: PublishJob) -> PublishedContent | None:
    """The job's ``PublishedContent``, created on first call. None when the job has no remote
    video yet or its edit no longer exists."""
    if not job.provider_video_id:
        return None
    existing = content_for_job(db, job) or db.scalar(
        select(PublishedContent).where(
            PublishedContent.provider == job.provider,
            PublishedContent.remote_video_id == job.provider_video_id,
        )
    )
    if existing is not None:
        if existing.publish_job_id == job.id:
            return existing
        # The remote id is already linked to another job: YouTube never gives two uploads one
        # id, so this is a simulated id reused across processes. Never borrow another job's
        # (let alone another creator's) row.
        logger.warning("Publish job %s: remote id already linked to another job; not linked",
                       job.id)  # fmt: skip
        return None
    edit = db.get(ClipEdit, job.edit_id)
    if edit is None:
        return None
    clip = edit.clip
    plan = _applied_plan(db, edit)
    content = PublishedContent(
        user_id=job.user_id,
        project_id=clip.video.project_id,
        clip_id=clip.id,
        edit_id=edit.id,
        auto_edit_plan_id=plan.id if plan is not None else None,
        publish_job_id=job.id,
        provider=job.provider,
        remote_video_id=job.provider_video_id,
        title=job.title,
        published_at=job.completed_at or datetime.now(UTC),
        duration_seconds=edit.duration_seconds,
        privacy=job.privacy,
        remote_status=RemoteStatus.ACTIVE,
        provenance=build_provenance(edit, plan, clip.candidate),
        provenance_version=PROVENANCE_VERSION,
        # First metrics a few hours in; synced only once the creator granted analytics access.
        next_sync_at=(job.completed_at or datetime.now(UTC)) + FIRST_SYNC_AFTER,
    )
    db.add(content)
    try:
        db.commit()
    except IntegrityError:  # linked concurrently by another worker: use that row
        db.rollback()
        return content_for_job(db, job)
    logger.info("Publish job %s linked to published content %s", job.id, content.id)
    return content


def link_quietly(db: Session, job: PublishJob) -> None:
    """For the publishing pipeline: analytics bookkeeping never fails a publish."""
    try:
        link_published_content(db, job)
    except Exception:
        logger.exception("Could not link publish job %s to published content", job.id)
        db.rollback()


def link_existing(db: Session, user_id: uuid.UUID) -> int:
    """Link every uploaded job of ``user_id`` that has no content yet (published before
    V1.4, or a link that failed). Returns how many were linked."""
    jobs = db.scalars(
        select(PublishJob).where(
            PublishJob.user_id == user_id,
            PublishJob.provider_video_id.is_not(None),
            ~select(PublishedContent.id)
            .where(PublishedContent.publish_job_id == PublishJob.id)
            .exists(),
        )
    ).all()
    linked = 0
    for job in jobs:
        if link_published_content(db, job) is not None:
            linked += 1
    return linked
