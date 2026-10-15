"""Generate, inspect and retry rendered clips for AI candidates.

Ownership is the full chain User → Project → Video → Run → Candidate → Clip (the candidate
dependencies from the clip-detection router already enforce the first five links); anything
outside it is an indistinguishable 404. Boundaries always come from the persisted,
validated candidate — never from the request body.

Decision semantics: an ``undecided`` or ``saved`` candidate may be rendered; a ``dismissed``
one must be restored first (the UI offers Restore). A clip that already exists is never
destroyed because the candidate's decision changes afterwards.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.clip_detection import OwnedCandidate
from app.api.deps import DbSession, Storage
from app.api.media_streaming import object_present
from app.api.transcriptions import OwnedVideo
from app.core.config import get_settings
from app.models import CandidateDecision, Clip, ClipCandidate, ClipStatus, Video, VideoStatus
from app.schemas.clip import ClipPage, ClipRead
from app.services.clip_render.pipeline import is_stale
from app.services.clip_render.renderer import RenderError, validate_range
from app.services.storage import StorageProvider
from app.workers.dispatch import JobQueueUnavailable, enqueue_clip_render, new_task_id

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clip-detection/{run_id}/candidates/{candidate_id}",
    tags=["clips"],
)
video_clips_router = APIRouter(prefix="/projects/{project_id}/videos/{video_id}", tags=["clips"])

MAX_PAGE_SIZE = 100

logger = logging.getLogger(__name__)


def _read(clip: Clip, title: str, run_id: uuid.UUID) -> ClipRead:
    return ClipRead(
        id=clip.id,
        candidate_id=clip.candidate_id,
        run_id=run_id,
        video_id=clip.video_id,
        title=title,
        status=clip.status,
        progress_percent=clip.progress_percent,
        attempt=clip.attempt,
        is_stale=is_stale(clip, get_settings()),
        start_time=clip.start_time,
        end_time=clip.end_time,
        duration_seconds=clip.duration_seconds,
        render_profile=clip.render_profile,
        content_type=clip.content_type,
        file_size=clip.file_size,
        width=clip.width,
        height=clip.height,
        fps=clip.fps,
        video_codec=clip.video_codec,
        audio_codec=clip.audio_codec,
        error_code=clip.error_code,
        error_message=clip.error_message,
        created_at=clip.created_at,
        started_at=clip.started_at,
        completed_at=clip.completed_at,
    )


def _read_for(clip: Clip) -> ClipRead:
    return _read(clip, clip.candidate.title, clip.candidate.run_id)


def _reconcile(db: DbSession, clip: Clip | None, storage: StorageProvider) -> Clip | None:
    """``ready`` must mean a file exists. If the artifact vanished (disk loss, manual
    deletion), say so honestly and make the clip retryable instead of a dead end."""
    if clip is None or clip.status != ClipStatus.READY:
        return clip
    present = object_present(storage, clip.storage_key)
    if not present:
        logger.error("Clip %s was ready but its artifact is missing; marking failed", clip.id)
        clip.status = ClipStatus.FAILED
        clip.error_code = "artifact_missing"
        clip.error_message = "The rendered file is missing; retry to render it again"
        clip.storage_key = None
        db.commit()
    return clip


def _existing_clip(db: DbSession, candidate: ClipCandidate) -> Clip | None:
    return db.scalar(select(Clip).where(Clip.candidate_id == candidate.id))


def _require_ready_video(video: Video) -> None:
    if video.status != VideoStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The source video is not ready"
        )


def _enqueue_or_503(db: DbSession, clip: Clip, *, created: bool) -> None:
    """The task id is already on the committed row; now hand the job to the broker."""
    try:
        enqueue_clip_render(clip.id, task_id=clip.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(clip)  # never leave a queued row that no worker will pick up
        else:
            clip.status = ClipStatus.FAILED
            clip.error_code = "queue_unavailable"
            clip.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The rendering queue is unavailable. Try again in a moment.",
        ) from None


# --- generate / status / retry ---------------------------------------------------------------


@router.post("/clip", response_model=ClipRead, status_code=status.HTTP_201_CREATED)
def generate_clip(
    candidate: OwnedCandidate,
    video: OwnedVideo,
    db: DbSession,
    storage: Storage,
    response: Response,
) -> ClipRead:
    """Render this candidate. Idempotent: an existing queued/rendering/ready clip is returned
    (200) instead of duplicated; a failed one must be retried explicitly (409)."""
    existing = _reconcile(db, _existing_clip(db, candidate), storage)
    if existing is not None:
        if existing.status == ClipStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last render failed; use the retry endpoint",
            )
        response.status_code = status.HTTP_200_OK
        return _read(existing, candidate.title, candidate.run_id)

    _require_ready_video(video)
    if candidate.decision == CandidateDecision.DISMISSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Restore the dismissed candidate before generating a clip",
        )
    settings = get_settings()
    try:
        duration = validate_range(
            candidate.start_time,
            candidate.end_time,
            video.duration_seconds,
            settings.clip_render_source_tolerance_seconds,
        )
    except RenderError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message) from None

    clip = Clip(
        candidate_id=candidate.id,
        video_id=video.id,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        duration_seconds=duration,
        celery_task_id=new_task_id(),  # fencing token committed before the job exists
    )
    db.add(clip)
    try:
        db.commit()
    except IntegrityError:  # a concurrent generate won the unique candidate constraint
        db.rollback()
        existing = _existing_clip(db, candidate)
        if existing is None:  # pragma: no cover - the other transaction vanished
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Try again") from None
        response.status_code = status.HTTP_200_OK
        return _read(existing, candidate.title, candidate.run_id)
    _enqueue_or_503(db, clip, created=True)
    return _read(clip, candidate.title, candidate.run_id)


@router.get("/clip", response_model=ClipRead)
def get_clip(candidate: OwnedCandidate, db: DbSession, storage: Storage) -> ClipRead:
    clip = _reconcile(db, _existing_clip(db, candidate), storage)
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clip generated yet")
    return _read(clip, candidate.title, candidate.run_id)


@router.post("/clip/retry", response_model=ClipRead)
def retry_clip(
    candidate: OwnedCandidate, video: OwnedVideo, db: DbSession, storage: Storage
) -> ClipRead:
    """Re-queue a failed or stalled render on the same clip row (same boundaries)."""
    clip = _reconcile(db, _existing_clip(db, candidate), storage)
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clip generated yet")
    settings = get_settings()
    if clip.status != ClipStatus.FAILED and not is_stale(clip, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled render can be retried",
        )
    if clip.attempt >= settings.clip_render_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This clip has been retried too many times",
        )
    _require_ready_video(video)

    clip.status = ClipStatus.QUEUED
    clip.progress_percent = 0
    clip.attempt += 1
    clip.error_code = None
    clip.error_message = None
    clip.started_at = None
    clip.completed_at = None
    clip.heartbeat_at = None
    clip.celery_task_id = new_task_id()  # a zombie worker from the old attempt is fenced out
    db.commit()
    _enqueue_or_503(db, clip, created=False)
    return _read(clip, candidate.title, candidate.run_id)


# --- per-video listing ---------------------------------------------------------------------------


@video_clips_router.get("/clips", response_model=ClipPage)
def list_clips(
    video: OwnedVideo,
    db: DbSession,
    storage: Storage,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> ClipPage:
    """Every generated clip of the video (any status), newest first."""
    total = db.scalar(select(func.count()).select_from(Clip).where(Clip.video_id == video.id)) or 0
    clips = db.scalars(
        select(Clip)
        .where(Clip.video_id == video.id)
        .order_by(Clip.created_at.desc(), Clip.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    clips = [_reconcile(db, clip, storage) for clip in clips]
    return ClipPage(total=total, offset=offset, limit=limit, clips=[_read_for(c) for c in clips])
