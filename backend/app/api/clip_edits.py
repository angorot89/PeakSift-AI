"""Short-form edits of generated clips: create (idempotent per configuration), list,
status, retry, and private preview/download of the edited short.

Ownership chain: User → Project → Video → Clip → ClipEdit; anything else is a 404 (401 without
a session). Clients send only allow-listed options (``EditRequest``); the server normalizes
them, so equivalent requests — a double click, a network retry, two tabs — resolve to the
same edit through the unique ``(clip_id, config_fingerprint)`` constraint.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import stream_file
from app.api.transcriptions import OwnedVideo
from app.core.config import get_settings
from app.models import (
    Clip,
    ClipEdit,
    ClipEditStatus,
    ClipStatus,
    Project,
    TranscriptionStatus,
    Video,
)
from app.schemas.clip_edit import ClipEditPage, ClipEditRead, EditRequest
from app.services.clip_edit.composition import supports_captions
from app.services.clip_edit.config import (
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    RENDER_PROFILE_VERTICAL_V1,
    EditConfig,
)
from app.services.clip_edit.pipeline import is_stale
from app.services.clip_render.storage import safe_download_filename
from app.services.storage import InvalidStorageKey, LocalMediaStorage
from app.workers.dispatch import JobQueueUnavailable, enqueue_clip_edit, new_task_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clips/{clip_id}/edits", tags=["edits"]
)
media_router = APIRouter(prefix="/edits", tags=["edits"])

MAX_PAGE_SIZE = 50


def get_owned_clip(clip_id: uuid.UUID, video: OwnedVideo, db: DbSession) -> Clip:
    clip = db.scalar(select(Clip).where(Clip.id == clip_id, Clip.video_id == video.id))
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")
    return clip


OwnedClip = Annotated[Clip, Depends(get_owned_clip)]


def get_owned_edit(edit_id: uuid.UUID, clip: OwnedClip, db: DbSession) -> ClipEdit:
    edit = db.scalar(select(ClipEdit).where(ClipEdit.id == edit_id, ClipEdit.clip_id == clip.id))
    if edit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edit not found")
    return edit


OwnedEdit = Annotated[ClipEdit, Depends(get_owned_edit)]


def _read(edit: ClipEdit) -> ClipEditRead:
    return ClipEditRead(
        id=edit.id,
        clip_id=edit.clip_id,
        video_id=edit.video_id,
        status=edit.status,
        progress_percent=edit.progress_percent,
        attempt=edit.attempt,
        is_stale=is_stale(edit, get_settings()),
        configuration=edit.config,
        aspect_ratio=edit.aspect_ratio,
        layout=edit.layout,
        captions_enabled=edit.captions_enabled,
        caption_style=edit.caption_style,
        caption_position=edit.caption_position,
        output_width=edit.output_width,
        output_height=edit.output_height,
        render_profile=edit.render_profile,
        caption_cue_count=edit.caption_cue_count,
        duration_seconds=edit.duration_seconds,
        width=edit.width,
        height=edit.height,
        fps=edit.fps,
        file_size=edit.file_size,
        video_codec=edit.video_codec,
        audio_codec=edit.audio_codec,
        error_code=edit.error_code,
        error_message=edit.error_message,
        created_at=edit.created_at,
        started_at=edit.started_at,
        completed_at=edit.completed_at,
    )


def _reconcile(db: DbSession, edit: ClipEdit | None, storage: LocalMediaStorage) -> ClipEdit | None:
    """``ready`` must mean the file exists; a vanished artifact becomes a retryable failure."""
    if edit is None or edit.status != ClipEditStatus.READY:
        return edit
    try:
        present = bool(edit.storage_key) and storage.path_for(edit.storage_key).is_file()
    except InvalidStorageKey:
        present = False
    if not present:
        logger.error("Clip edit %s was ready but its artifact is missing; marking failed", edit.id)
        edit.status = ClipEditStatus.FAILED
        edit.error_code = "artifact_missing"
        edit.error_message = "The edited file is missing; retry to render it again"
        edit.storage_key = None
        db.commit()
    return edit


def _existing(db: DbSession, clip: Clip, fingerprint: str) -> ClipEdit | None:
    return db.scalar(
        select(ClipEdit).where(
            ClipEdit.clip_id == clip.id, ClipEdit.config_fingerprint == fingerprint
        )
    )


def _require_renderable(clip: Clip, video: Video, config: EditConfig) -> None:
    if clip.status != ClipStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Generate the clip before editing it"
        )
    if config.captions_enabled:
        transcription = video.transcription
        if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Captions need a completed transcript for this video",
            )
        if not supports_captions(get_settings().ffmpeg_path):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Captions are not available on this server (FFmpeg has no libass)",
            )


def _enqueue_or_503(db: DbSession, edit: ClipEdit, *, created: bool) -> None:
    """The attempt token is already committed on the row; hand the job to the broker."""
    try:
        enqueue_clip_edit(edit.id, task_id=edit.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(edit)  # never leave a queued row that no worker will pick up
        else:
            edit.status = ClipEditStatus.FAILED
            edit.error_code = "queue_unavailable"
            edit.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The rendering queue is unavailable. Try again in a moment.",
        ) from None


# --- create / list / status / retry ------------------------------------------------------------


@router.post("", response_model=ClipEditRead, status_code=status.HTTP_201_CREATED)
def create_edit(
    body: EditRequest,
    clip: OwnedClip,
    video: OwnedVideo,
    db: DbSession,
    storage: Storage,
    response: Response,
) -> ClipEditRead:
    """Render the clip as a 9:16 short with these options. The same (normalized) options
    return the existing edit (200); a failed one must be retried explicitly (409)."""
    try:
        config = EditConfig.create(
            aspect_ratio=body.aspect_ratio,
            layout=body.layout,
            captions_enabled=body.captions_enabled,
            caption_style=body.caption_style,
            caption_position=body.caption_position,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from None
    fingerprint = config.fingerprint()

    existing = _reconcile(db, _existing(db, clip, fingerprint), storage)
    if existing is not None:
        if existing.status == ClipEditStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last render of these settings failed; use the retry endpoint",
            )
        response.status_code = status.HTTP_200_OK
        return _read(existing)

    _require_renderable(clip, video, config)
    edit = ClipEdit(
        clip_id=clip.id,
        video_id=video.id,
        config=config.snapshot(),
        config_fingerprint=fingerprint,
        aspect_ratio=config.aspect_ratio.value,
        layout=config.layout.value,
        captions_enabled=config.captions_enabled,
        caption_style=config.caption_style.value if config.caption_style else None,
        caption_position=config.caption_position.value if config.caption_position else None,
        output_width=OUTPUT_WIDTH,
        output_height=OUTPUT_HEIGHT,
        render_profile=RENDER_PROFILE_VERTICAL_V1,
        celery_task_id=new_task_id(),  # attempt token committed before the job exists
    )
    db.add(edit)
    try:
        db.commit()
    except IntegrityError:  # a concurrent identical request won the unique constraint
        db.rollback()
        winner = _existing(db, clip, fingerprint)
        if winner is None:  # pragma: no cover - the other transaction vanished
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Try again") from None
        response.status_code = status.HTTP_200_OK
        return _read(winner)
    _enqueue_or_503(db, edit, created=True)
    return _read(edit)


@router.get("", response_model=ClipEditPage)
def list_edits(
    clip: OwnedClip,
    db: DbSession,
    storage: Storage,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> ClipEditPage:
    """The clip's edit variants, newest first."""
    total = (
        db.scalar(select(func.count()).select_from(ClipEdit).where(ClipEdit.clip_id == clip.id))
        or 0
    )
    edits = db.scalars(
        select(ClipEdit)
        .where(ClipEdit.clip_id == clip.id)
        .order_by(ClipEdit.created_at.desc(), ClipEdit.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    edits = [_reconcile(db, edit, storage) for edit in edits]
    return ClipEditPage(total=total, offset=offset, limit=limit, edits=[_read(e) for e in edits])


@router.get("/{edit_id}", response_model=ClipEditRead)
def get_edit(edit: OwnedEdit, db: DbSession, storage: Storage) -> ClipEditRead:
    return _read(_reconcile(db, edit, storage))


@router.post("/{edit_id}/retry", response_model=ClipEditRead)
def retry_edit(
    edit: OwnedEdit, clip: OwnedClip, video: OwnedVideo, db: DbSession, storage: Storage
) -> ClipEditRead:
    """Re-queue a failed or stalled edit on the same row with a fresh attempt token."""
    settings = get_settings()
    edit = _reconcile(db, edit, storage)
    if edit.status != ClipEditStatus.FAILED and not is_stale(edit, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled edit can be retried",
        )
    if edit.attempt >= settings.clip_render_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This edit has been retried too many times"
        )
    _require_renderable(clip, video, EditConfig.from_snapshot(edit.config))
    edit.status = ClipEditStatus.QUEUED
    edit.progress_percent = 0
    edit.attempt += 1
    edit.error_code = None
    edit.error_message = None
    edit.started_at = None
    edit.completed_at = None
    edit.heartbeat_at = None
    edit.celery_task_id = new_task_id()  # fences out a stalled worker of the old attempt
    db.commit()
    _enqueue_or_503(db, edit, created=False)
    return _read(edit)


# --- private media ---------------------------------------------------------------------------


def _owned_ready_edit(edit_id: uuid.UUID, user_id: uuid.UUID, db, storage):
    edit = db.scalar(
        select(ClipEdit)
        .join(Video, ClipEdit.video_id == Video.id)
        .join(Project, Video.project_id == Project.id)
        .where(ClipEdit.id == edit_id, Project.user_id == user_id)
    )
    if edit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edit not found")
    if edit.status != ClipEditStatus.READY or not edit.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edit is not ready")
    try:
        path = storage.path_for(edit.storage_key)
    except InvalidStorageKey:
        logger.error("Clip edit %s has an invalid storage key", edit.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Edit file not found"
        ) from None
    if not path.is_file():
        logger.error("Clip edit %s is ready but its artifact is missing", edit.id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edit file not found")
    return edit, path


@media_router.get("/{edit_id}/content")
def edit_content(
    edit_id: uuid.UUID, request: Request, current_user: CurrentUser, db: DbSession, storage: Storage
) -> StreamingResponse:
    """Inline, Range-capable stream of the edited short for the browser's <video>."""
    edit, path = _owned_ready_edit(edit_id, current_user.id, db, storage)
    name = safe_download_filename(edit.clip.candidate.title, edit.id, variant="vertical")
    return stream_file(path, request, media_type=edit.content_type, filename=name)


@media_router.get("/{edit_id}/download")
def edit_download(
    edit_id: uuid.UUID, request: Request, current_user: CurrentUser, db: DbSession, storage: Storage
) -> StreamingResponse:
    """The edited short as an attachment named ``<title-slug>-vertical-<id>.mp4``."""
    edit, path = _owned_ready_edit(edit_id, current_user.id, db, storage)
    name = safe_download_filename(edit.clip.candidate.title, edit.id, variant="vertical")
    return stream_file(path, request, media_type=edit.content_type, filename=name, attachment=True)
