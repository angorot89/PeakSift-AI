"""Publishing an edited short, and following the job.

- ``GET /edits/{edit_id}/publish`` — the dialog's data: whether publishing is enabled, the
  connection, whether the edit is ready, the prefill (the clip's own title and hook, no AI;
  private) and this edit's publish history.
- ``POST /edits/{edit_id}/publish`` — publish with the reviewed metadata. ``201`` for a new
  job; ``200`` with the existing job when the same request was made before (never a second
  upload). ``422`` names the field that breaks YouTube's rules; ``409`` when the edit is
  not ready, no account is connected or it needs reconnecting, or publishing is disabled.
  With ``scheduled_at`` the job waits in ``scheduled`` and is released at that time by the
  scheduler (``services/publishing/schedule.py``); one Short has at most one waiting post.
- ``GET /publish-jobs?from=&to=`` — the calendar: the creator's posts in a time range.
- ``PATCH /publish-jobs/{job_id}/schedule``, ``POST …/publish-now``, ``DELETE …`` — move,
  release or cancel a post that is still waiting (``409`` once it is not).
- ``GET /publish-jobs/{job_id}`` — status and real progress.
- ``POST /publish-jobs/{job_id}/retry`` — only a job that failed before YouTube created a
  video (or stalled); it resumes the stored upload session.

Everything is owner-scoped (``404`` for anyone else, ``401`` signed out). Responses never
contain tokens, upload session URIs, task ids or storage keys.
"""

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import object_present
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import (
    ClipEdit,
    ClipEditStatus,
    ConnectionStatus,
    Project,
    PublishJob,
    PublishStatus,
    Video,
)
from app.schemas.publishing import (
    CalendarItem,
    CalendarRead,
    PublishDefaults,
    PublishingConnectionRead,
    PublishJobRead,
    PublishPanelRead,
    PublishRequest,
    ScheduleChange,
)
from app.services.publishing import connections, schedule
from app.services.publishing.jobs import PublishRefused, request_publish
from app.services.publishing.metadata import MetadataError, PublishMetadata, prefill
from app.services.publishing.pipeline import awaiting_processing, is_stale
from app.workers.dispatch import JobQueueUnavailable, enqueue_publish, new_task_id

edit_router = APIRouter(prefix="/edits/{edit_id}/publish", tags=["publishing"])
job_router = APIRouter(prefix="/publish-jobs", tags=["publishing"])


def _owned_edit(edit_id: uuid.UUID, user_id: uuid.UUID, db) -> ClipEdit:
    edit = db.scalar(
        select(ClipEdit)
        .join(Video, ClipEdit.video_id == Video.id)
        .join(Project, Video.project_id == Project.id)
        .where(ClipEdit.id == edit_id, Project.user_id == user_id)
    )
    if edit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edit not found")
    return edit


def _owned_job(job_id: uuid.UUID, user_id: uuid.UUID, db) -> PublishJob:
    job = db.scalar(
        select(PublishJob).where(PublishJob.id == job_id, PublishJob.user_id == user_id)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish job not found")
    return job


def _retryable(job: PublishJob) -> bool:
    stalled = is_stale(job, get_settings())
    failed_before_upload = job.status == PublishStatus.FAILED and not job.provider_video_id
    return (failed_before_upload or stalled) and job.attempt < get_settings().publish_max_attempts


def _read(job: PublishJob) -> PublishJobRead:
    video_id = job.provider_video_id
    simulated = bool(video_id) and job.provider == "youtube" and video_id.startswith("fake-")
    real = video_id and not simulated
    return PublishJobRead(
        id=job.id,
        edit_id=job.edit_id,
        provider=job.provider,
        status=job.status,
        progress_percent=job.progress_percent,
        bytes_uploaded=job.bytes_uploaded,
        bytes_total=job.bytes_total,
        title=job.title,
        description=job.description,
        tags=list(job.tags or []),
        privacy=job.privacy,
        made_for_kids=job.made_for_kids,
        video_url=f"https://youtu.be/{video_id}" if real else None,
        studio_url=f"https://studio.youtube.com/video/{video_id}/edit" if real else None,
        simulated=simulated,
        error_code=job.error_code,
        error_message=job.error_message,
        retryable=_retryable(job),
        is_stale=is_stale(job, get_settings()),
        awaiting_processing=awaiting_processing(job, get_settings()),
        attempt=job.attempt,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        published_at=job.published_at,
        scheduled_at=job.scheduled_at,
    )


def _ready(edit: ClipEdit, storage) -> bool:
    return edit.status == ClipEditStatus.READY and object_present(storage, edit.storage_key)


def _enqueue_or_503(db: DbSession, job: PublishJob, *, created: bool) -> None:
    try:
        enqueue_publish(job.id, task_id=job.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(job)  # never leave a queued row that no worker will pick up
        else:
            job.status = PublishStatus.FAILED
            job.error_code = "queue_unavailable"
            job.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The publishing queue is unavailable. Try again in a moment.",
        ) from None


def _when(value: datetime) -> datetime:
    try:
        return schedule.validate_time(value)
    except schedule.ScheduleError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"type": "schedule", "loc": ["body", "scheduled_at"], "msg": error.message}],
        ) from None


def _scheduled_job(job_id: uuid.UUID, user_id: uuid.UUID, db) -> PublishJob:
    """The owner's job, locked, and still waiting for its time — otherwise 404 or 409."""
    job = _owned_job(job_id, user_id, db)
    db.refresh(job, with_for_update=True)  # the scheduler may be releasing it right now
    if job.status != PublishStatus.SCHEDULED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This post is no longer waiting for its time",
        )
    return job


@edit_router.get("", response_model=PublishPanelRead)
def publish_panel(
    edit_id: uuid.UUID, current_user: CurrentUser, db: DbSession, storage: Storage
) -> PublishPanelRead:
    edit = _owned_edit(edit_id, current_user.id, db)
    candidate = edit.clip.candidate
    connection = connections.get_connection(db, current_user.id)
    jobs = db.scalars(
        select(PublishJob)
        .where(PublishJob.edit_id == edit.id, PublishJob.user_id == current_user.id)
        .order_by(PublishJob.created_at.desc())
    ).all()
    return PublishPanelRead(
        enabled=get_settings().youtube_publishing_enabled,
        connection=PublishingConnectionRead.model_validate(connection) if connection else None,
        edit_ready=_ready(edit, storage),
        defaults=PublishDefaults(**prefill(candidate.title, candidate.hook)),
        jobs=[_read(job) for job in jobs],
    )


@edit_router.post(
    "",
    response_model=PublishJobRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("publish_start")],
)
def publish(
    edit_id: uuid.UUID,
    payload: PublishRequest,
    response: Response,
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> PublishJobRead:
    edit = _owned_edit(edit_id, current_user.id, db)
    if not get_settings().youtube_publishing_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="YouTube publishing is not enabled on this server",
        )
    try:
        metadata = PublishMetadata.create(**payload.model_dump(exclude={"scheduled_at"}))
    except MetadataError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"type": "metadata", "loc": ["body", error.field], "msg": error.message}],
        ) from None
    if not _ready(edit, storage):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Render the short before publishing it"
        )
    when = _when(payload.scheduled_at) if payload.scheduled_at else None
    waiting = schedule.scheduled_for_edit(db, current_user.id, edit.id)
    try:
        job, created = request_publish(
            db, user_id=current_user.id, edit=edit, metadata=metadata, task_id=new_task_id(),
            connection=connections.get_connection(db, current_user.id), scheduled_at=when,
        )  # fmt: skip
    except PublishRefused as refused:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refused.message) from None
    if created and waiting is not None:
        # One Short, one pending post: a second request must change or cancel the first.
        db.delete(job)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Short is already scheduled. Change its time, publish it now or cancel it.",
        )
    if not created:
        response.status_code = status.HTTP_200_OK
        if when and job.status == PublishStatus.SCHEDULED and job.scheduled_at != when:
            job.scheduled_at = when  # the same post, asked for at a new time
            db.commit()
    elif when is None:
        _enqueue_or_503(db, job, created=True)
    return _read(job)


MAX_CALENDAR_DAYS = 62


@job_router.get("", response_model=CalendarRead)
def calendar(
    current_user: CurrentUser,
    db: DbSession,
    start: Annotated[datetime, Query(alias="from", description="Inclusive, with a time zone")],
    end: Annotated[datetime, Query(alias="to", description="Exclusive, with a time zone")],
) -> CalendarRead:
    """The creator's posts in a time range: scheduled ones at their time, the others when they
    were published (or started). Newest and oldest alike, in calendar order."""
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Send a valid range with time zones",
        )
    if end - start > timedelta(days=MAX_CALENDAR_DAYS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A calendar range covers at most {MAX_CALENDAR_DAYS} days",
        )
    at = func.coalesce(
        PublishJob.scheduled_at,
        PublishJob.published_at,
        PublishJob.completed_at,
        PublishJob.created_at,
    )
    rows = db.execute(
        select(PublishJob, ClipEdit, Project, at.label("at"))
        .join(ClipEdit, ClipEdit.id == PublishJob.edit_id)
        .join(Video, Video.id == ClipEdit.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(PublishJob.user_id == current_user.id, at >= start, at < end)
        .order_by(at, PublishJob.id)
        .limit(500)
    ).all()
    connection = connections.get_connection(db, current_user.id)
    return CalendarRead(
        items=[
            CalendarItem(
                job=_read(job),
                at=when,
                short_title=edit.clip.candidate.title,
                project_id=project.id,
                project_name=project.name,
                clip_id=edit.clip_id,
            )
            for job, edit, project, when in rows
        ],
        connection_ready=connection is not None and connection.status == ConnectionStatus.CONNECTED,
    )


@job_router.patch("/{job_id}/schedule", response_model=PublishJobRead)
def reschedule(
    job_id: uuid.UUID, payload: ScheduleChange, current_user: CurrentUser, db: DbSession
) -> PublishJobRead:
    """Move a post that is still waiting to a new time."""
    when = _when(payload.scheduled_at)
    job = _scheduled_job(job_id, current_user.id, db)
    job.scheduled_at = when
    db.commit()
    return _read(job)


@job_router.post(
    "/{job_id}/publish-now",
    response_model=PublishJobRead,
    dependencies=[per_user("publish_start")],
)
def publish_now(
    job_id: uuid.UUID, current_user: CurrentUser, db: DbSession, storage: Storage
) -> PublishJobRead:
    """Stop waiting: publish a scheduled post now, through the ordinary pipeline."""
    job = _scheduled_job(job_id, current_user.id, db)
    edit = db.get(ClipEdit, job.edit_id)
    if edit is None or not _ready(edit, storage):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Render the short before publishing it"
        )
    job.status = PublishStatus.QUEUED
    job.celery_task_id = new_task_id()
    db.commit()
    try:
        enqueue_publish(job.id, task_id=job.celery_task_id)
    except JobQueueUnavailable:
        job.status = PublishStatus.SCHEDULED  # still scheduled; nothing was lost
        job.celery_task_id = None
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The publishing queue is unavailable. Try again in a moment.",
        ) from None
    return _read(job)


@job_router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_scheduled(job_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Response:
    """Cancel a post that is still waiting. Anything already uploading or on YouTube is not
    touched by this (409): PeakSift never deletes a published video."""
    job = _scheduled_job(job_id, current_user.id, db)
    db.delete(job)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@job_router.get("/{job_id}", response_model=PublishJobRead)
def get_publish_job(job_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> PublishJobRead:
    return _read(_owned_job(job_id, current_user.id, db))


@job_router.post(
    "/{job_id}/retry", response_model=PublishJobRead, dependencies=[per_user("publish_start")]
)
def retry_publish_job(
    job_id: uuid.UUID, current_user: CurrentUser, db: DbSession, storage: Storage
) -> PublishJobRead:
    """Resume a job that failed before YouTube created a video, or that stalled."""
    job = _owned_job(job_id, current_user.id, db)
    db.refresh(job, with_for_update=True)  # concurrent retries serialize; the second gets 409
    if job.provider_video_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This short is already on YouTube; it will not be uploaded again",
        )
    if not _retryable(job):
        if job.attempt >= get_settings().publish_max_attempts:
            detail = "This publish has been retried too many times"
        else:
            detail = "Only a failed or stalled publish can be retried"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    edit = db.get(ClipEdit, job.edit_id)
    if edit is None or not _ready(edit, storage):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Render the short before publishing it"
        )
    job.status = PublishStatus.QUEUED
    job.attempt += 1
    job.error_code = job.error_message = None
    job.started_at = job.completed_at = job.heartbeat_at = None
    job.celery_task_id = new_task_id()  # fences out a stalled worker of the old attempt
    db.commit()
    _enqueue_or_503(db, job, created=False)
    return _read(job)
