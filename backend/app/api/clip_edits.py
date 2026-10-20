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
from app.api.media_streaming import object_present, stream_object
from app.api.transcriptions import OwnedVideo
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import (
    AudioAsset,
    AudioAssetKind,
    CaptionTrack,
    CaptionTrackStatus,
    Clip,
    ClipEdit,
    ClipEditStatus,
    ClipStatus,
    Project,
    ReframeAnalysis,
    ReframeStatus,
    TranscriptionStatus,
    Video,
)
from app.schemas.clip_edit import ClipEditPage, ClipEditRead, EditRequest
from app.schemas.project import MediaDeletionRead
from app.services.clip_edit.composition import supports_captions, supports_visuals
from app.services.clip_edit.config import (
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    RENDER_PROFILE_VERTICAL_V1,
    CaptionTiming,
    EditConfig,
    Layout,
)
from app.services.clip_edit.pipeline import is_stale
from app.services.clip_render.storage import safe_download_filename
from app.services.media_deletion import delete_edit as delete_edit_and_media
from app.services.storage import StorageProvider
from app.services.visuals.assets import VisualsProblem, check_visuals, load_visual_assets
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


def read_edit(edit: ClipEdit) -> ClipEditRead:
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
        caption_renderer=edit.caption_renderer,
        caption_timing=edit.caption_timing,
        caption_track_id=edit.caption_track_id,
        reframe_analysis_id=edit.reframe_analysis_id,
        focus_x=edit.focus_x,
        focus_y=edit.focus_y,
        hook_enabled=edit.hook_enabled,
        hook_text=edit.hook_text,
        hook_style=edit.hook_style,
        hook_position=edit.hook_position,
        hook_duration_seconds=edit.hook_duration_seconds,
        output_width=edit.output_width,
        output_height=edit.output_height,
        render_profile=edit.render_profile,
        caption_cue_count=edit.caption_cue_count,
        audio_loudness_lufs=edit.audio_loudness_lufs,
        audio_true_peak_dbtp=edit.audio_true_peak_dbtp,
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


def _reconcile(db: DbSession, edit: ClipEdit | None, storage: StorageProvider) -> ClipEdit | None:
    """``ready`` must mean the file exists; a vanished artifact becomes a retryable failure."""
    if edit is None or edit.status != ClipEditStatus.READY:
        return edit
    present = object_present(storage, edit.storage_key)
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


def _require_renderable(db: DbSession, clip: Clip, video: Video, config: EditConfig) -> None:
    if clip.status != ClipStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Generate the clip before editing it"
        )
    if config.layout == Layout.SMART_REFRAME:
        analysis = db.get(ReframeAnalysis, uuid.UUID(str(config.reframe_analysis_id)))
        # Another clip's analysis is indistinguishable from a missing one (no existence leak).
        if (
            analysis is None
            or analysis.clip_id != clip.id
            or analysis.status != ReframeStatus.COMPLETED
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Analyze the framing of this clip before rendering a smart reframe",
            )
    if config.hook is not None and not supports_captions(get_settings().ffmpeg_path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Text overlays are not available on this server",
        )
    if config.captions_enabled and config.caption_timing == CaptionTiming.ALIGNED_WORD:
        track = db.get(CaptionTrack, uuid.UUID(str(config.caption_track_id)))
        # Another clip's track is indistinguishable from a missing one (no existence leak).
        if (
            track is None
            or track.clip_id != clip.id
            or track.status != CaptionTrackStatus.COMPLETED
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Generate word timing for this clip first, or choose phrase timing",
            )
    elif config.captions_enabled:  # phrase captions (V0.6 or dynamic) come from the transcript
        transcription = video.transcription
        if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Captions need a completed transcript for this video",
            )
        if not supports_captions(get_settings().ffmpeg_path):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Captions are not available on this server",
            )


def _require_audio(db: DbSession, clip: Clip, video: Video, config: EditConfig) -> None:
    """Referenced audio must be this project's, of the right kind, and fit the clip."""
    mix = config.audio
    if mix is None:
        return
    ids = {uuid.UUID(asset_id) for asset_id in mix.asset_ids}
    assets = {
        asset.id: asset
        for asset in db.scalars(
            select(AudioAsset).where(
                AudioAsset.id.in_(ids), AudioAsset.project_id == video.project_id
            )
        )
    }
    # Another project's asset is indistinguishable from a missing one (no existence leak).
    if mix.music is not None:
        music = assets.get(uuid.UUID(mix.music.asset_id))
        if music is None or music.kind != AudioAssetKind.MUSIC:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Choose background music from this project's audio",
            )
        if mix.music.source_start_seconds >= music.duration_seconds:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The music start is after the end of the track",
            )
    for cue in mix.sfx:
        effect = assets.get(uuid.UUID(cue.asset_id))
        if effect is None or effect.kind != AudioAssetKind.SFX:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Choose sound effects from this project's audio",
            )
        if cue.at_seconds > float(clip.duration_seconds):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A sound effect starts after the end of the clip",
            )


def _require_visuals(db: DbSession, clip: Clip, video: Video, config: EditConfig) -> None:
    """Referenced visuals must be this project's, suit their mode, and fit the clip."""
    if config.visuals is None:
        return
    if not supports_visuals(get_settings().ffmpeg_path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Visual elements are not available on this server",
        )
    assets = load_visual_assets(db, video.project_id, config.visuals.asset_ids)
    try:
        check_visuals(config.visuals, assets, float(clip.duration_seconds))
    except VisualsProblem as problem:
        # Another project's asset is indistinguishable from a missing one (no existence leak).
        raise HTTPException(status_code=problem.status, detail=problem.message) from None


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


@router.post(
    "",
    response_model=ClipEditRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("edit_render")],
)
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
            reframe_analysis_id=body.reframe_analysis_id,
            focus_x=body.focus_x,
            focus_y=body.focus_y,
            hook_enabled=body.hook_enabled,
            hook_text=body.hook_text,
            hook_style=body.hook_style,
            hook_position=body.hook_position,
            hook_duration=body.hook_duration_seconds,
            caption_timing=body.caption_timing,
            caption_track_id=body.caption_track_id,
            audio=body.audio.model_dump(mode="json") if body.audio else None,
            visuals=body.visuals.model_dump(mode="json") if body.visuals else None,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from None
    edit, created = create_or_reuse_edit(db, clip, video, storage, config)
    if not created:
        if edit.status == ClipEditStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last render of these settings failed; use the retry endpoint",
            )
        response.status_code = status.HTTP_200_OK
    return read_edit(edit)


def create_or_reuse_edit(
    db: DbSession, clip: Clip, video: Video, storage: StorageProvider, config: EditConfig
) -> tuple[ClipEdit, bool]:
    """The edit for this (normalized) configuration: the existing one (any status), or a new
    one checked like every request and queued for rendering. Shared by the edit endpoint and
    by applying an Auto Edit plan, so both go through exactly the same checks."""
    fingerprint = config.fingerprint()
    existing = _reconcile(db, _existing(db, clip, fingerprint), storage)
    if existing is not None:
        return existing, False

    _require_renderable(db, clip, video, config)
    _require_audio(db, clip, video, config)
    _require_visuals(db, clip, video, config)
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
        caption_renderer=config.caption_renderer,
        caption_timing=config.caption_timing.value if config.caption_timing else None,
        caption_track_id=uuid.UUID(config.caption_track_id) if config.caption_track_id else None,
        reframe_analysis_id=(
            uuid.UUID(config.reframe_analysis_id) if config.reframe_analysis_id else None
        ),
        focus_x=config.focus_x,
        focus_y=config.focus_y,
        hook_enabled=config.hook is not None,
        hook_text=config.hook.text if config.hook else None,
        hook_style=config.hook.style.value if config.hook else None,
        hook_position=config.hook.position.value if config.hook else None,
        hook_duration_seconds=config.hook.duration if config.hook else None,
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
        return winner, False
    _enqueue_or_503(db, edit, created=True)
    return edit, True


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
    return ClipEditPage(
        total=total, offset=offset, limit=limit, edits=[read_edit(e) for e in edits]
    )


@router.get("/{edit_id}", response_model=ClipEditRead)
def get_edit(edit: OwnedEdit, db: DbSession, storage: Storage) -> ClipEditRead:
    return read_edit(_reconcile(db, edit, storage))


@router.post(
    "/{edit_id}/retry", response_model=ClipEditRead, dependencies=[per_user("edit_render")]
)
def retry_edit(
    edit: OwnedEdit, clip: OwnedClip, video: OwnedVideo, db: DbSession, storage: Storage
) -> ClipEditRead:
    """Re-queue a failed or stalled edit on the same row with a fresh attempt token."""
    settings = get_settings()
    edit = _reconcile(db, edit, storage)  # may commit, so the lock is taken afterwards
    # Lock the row until the commit below: two concurrent retries serialize, and the second
    # one sees "queued" and gets 409 instead of enqueueing a duplicate render.
    db.refresh(edit, with_for_update=True)
    if edit.status != ClipEditStatus.FAILED and not is_stale(edit, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled edit can be retried",
        )
    if edit.attempt >= settings.clip_render_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This edit has been retried too many times"
        )
    stored = EditConfig.from_snapshot(edit.config)
    _require_renderable(db, clip, video, stored)
    _require_visuals(db, clip, video, stored)
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
    return read_edit(edit)


@router.delete("/{edit_id}", response_model=MediaDeletionRead)
def delete_edit(edit: OwnedEdit, db: DbSession, storage: Storage) -> MediaDeletionRead:
    """Delete an edit and its rendered short. The source clip is never touched. A render
    still running for it notices the edit is gone and discards its own output."""
    report = delete_edit_and_media(db, storage, edit)
    return MediaDeletionRead(
        media_files_removed=report.deleted, media_files_pending_cleanup=report.failed
    )


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
    if not object_present(storage, edit.storage_key):
        logger.error("Clip edit %s is ready but its artifact is missing", edit.id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edit file not found")
    return edit


@media_router.get("/{edit_id}/content")
def edit_content(
    edit_id: uuid.UUID, request: Request, current_user: CurrentUser, db: DbSession, storage: Storage
) -> StreamingResponse:
    """Inline, Range-capable stream of the edited short for the browser's <video>."""
    edit = _owned_ready_edit(edit_id, current_user.id, db, storage)
    name = safe_download_filename(edit.clip.candidate.title, edit.id, variant="vertical")
    return stream_object(
        storage, edit.storage_key, request, media_type=edit.content_type, filename=name
    )


@media_router.get("/{edit_id}/download")
def edit_download(
    edit_id: uuid.UUID, request: Request, current_user: CurrentUser, db: DbSession, storage: Storage
) -> StreamingResponse:
    """The edited short as an attachment named ``<title-slug>-vertical-<id>.mp4``."""
    edit = _owned_ready_edit(edit_id, current_user.id, db, storage)
    name = safe_download_filename(edit.clip.candidate.title, edit.id, variant="vertical")
    return stream_object(
        storage,
        edit.storage_key,
        request,
        media_type=edit.content_type,
        filename=name,
        attachment=True,
    )
