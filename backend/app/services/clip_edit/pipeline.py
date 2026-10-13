"""The short-form edit job: ClipEdit row → captions file → FFmpeg composition → validated
render → atomic finalize → ready.

Runs inside a Celery worker. The ``clip_edits`` row is the source of truth:

- **Claiming:** a ready edit is never re-rendered; a live edit (fresh heartbeat) is never
  rendered twice; a failed edit only re-runs after the retry endpoint resets it; a row
  whose task id belongs to a newer attempt is ignored.
- **Ownership:** the task id committed on the row before enqueueing is the attempt token.
  Every commit and the failure path re-read it, so a stalled worker that a retry took over
  cannot change the row; it only ever touches its own ``work-<attempt>`` directory.
- **Order of operations:** render into the attempt's workspace, validate with ffprobe,
  rename atomically to ``edited.mp4``, then one commit sets ``storage_key`` + metadata +
  ``ready`` — so ``ready`` always means a validated file exists.
- **Captions** come only from the persisted transcript (see ``captions.py``); the V0.5 clip
  file is the read-only video source and is never modified.

Progress is honest stage progress: 5 claimed, 15 captions prepared, 85 rendered,
90 validating, 100 ready.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    ClipEdit,
    ClipEditStatus,
    ClipStatus,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.services.clip_edit.caption_styles import build_ass_document
from app.services.clip_edit.captions import SourceSegment, build_cues
from app.services.clip_edit.composition import ComposedShort, compose_short
from app.services.clip_edit.config import EditConfig
from app.services.clip_edit.storage import EditArtifactStore
from app.services.clip_render.pipeline import render_options_from
from app.services.clip_render.renderer import RenderError
from app.services.storage import InvalidStorageKey, LocalMediaStorage, StorageError

logger = logging.getLogger(__name__)

CLAIMED_PROGRESS = 5
CAPTIONS_READY_PROGRESS = 15
RENDER_DONE_PROGRESS = 85
VALIDATING_PROGRESS = 90
MAX_ERROR_LENGTH = 500

Composer = Callable[..., ComposedShort]


class PipelineSuperseded(Exception):
    """A newer attempt owns this edit; stop without writing."""


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(edit: ClipEdit, settings: Settings, *, now: datetime | None = None) -> bool:
    if edit.status not in (ClipEditStatus.RENDERING, ClipEditStatus.VALIDATING):
        return False
    last = edit.heartbeat_at or edit.started_at or edit.created_at
    return ((now or _now()) - last).total_seconds() > settings.clip_render_stale_after_seconds


def run_clip_edit(
    edit_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: LocalMediaStorage | None = None,
    composer: Composer | None = None,
    task_id: str | None = None,
) -> ClipEdit | None:
    """Execute the render for a ``ClipEdit`` row. Problems are recorded, never raised."""
    settings = settings or get_settings()
    store = EditArtifactStore(storage or LocalMediaStorage(settings.media_root))
    composer = composer or compose_short  # resolved at call time (tests patch the module)

    edit = db.get(ClipEdit, edit_id)
    if edit is None:
        logger.warning("Clip edit %s no longer exists; nothing to render", edit_id)
        return None
    if not _claim(edit, db, settings, store, task_id):
        return edit
    attempt = edit.attempt

    def fail(code: str, message: str) -> None:
        _fail(edit, db, store, code, message, task_id=task_id, attempt=attempt)

    try:
        _execute(edit, db, settings, store, composer, task_id, attempt)
    except PipelineSuperseded:
        store.discard_workspace(edit.id, attempt)
        logger.info("Clip edit %s was taken over by a newer attempt; stopping", edit.id)
    except (PipelineFailure, RenderError) as error:
        fail(error.code, error.message)
    except StorageError:
        logger.exception("Storage failure while finalizing clip edit %s", edit.id)
        fail("storage_failure", "The edited short could not be stored")
    except SoftTimeLimitExceeded:
        fail("time_limit", "Rendering ran longer than the worker allows; retry the edit")
    except Exception:
        logger.exception("Unexpected error rendering clip edit %s", edit.id)
        fail("internal_error", "Unexpected error while rendering the short")
    return edit


# --- claiming -----------------------------------------------------------------------


def _claim(
    edit: ClipEdit, db: Session, settings: Settings, store: EditArtifactStore, task_id: str | None
) -> bool:
    if task_id and edit.celery_task_id and edit.celery_task_id != task_id:
        logger.info("Clip edit %s belongs to a newer attempt; ignoring", edit.id)
        return False
    if edit.status == ClipEditStatus.READY:
        logger.info("Clip edit %s is already ready; ignoring duplicate task", edit.id)
        return False
    if edit.status == ClipEditStatus.FAILED:
        logger.info("Clip edit %s is failed; a retry must reset it first", edit.id)
        return False
    if edit.status != ClipEditStatus.QUEUED and not is_stale(edit, settings):
        logger.info("Clip edit %s is already rendering elsewhere", edit.id)
        return False

    store.discard(edit.id)  # nothing from an earlier attempt survives (stale temp, orphans)
    now = _now()
    edit.status = ClipEditStatus.RENDERING
    edit.started_at = now
    edit.heartbeat_at = now
    edit.completed_at = None
    edit.progress_percent = CLAIMED_PROGRESS
    edit.error_code = None
    edit.error_message = None
    edit.storage_key = None
    edit.file_size = None
    edit.duration_seconds = None
    edit.width = edit.height = None
    edit.fps = None
    edit.video_codec = edit.audio_codec = None
    edit.caption_cue_count = None
    db.commit()
    return True


# --- the work -------------------------------------------------------------------------


def _execute(
    edit: ClipEdit,
    db: Session,
    settings: Settings,
    store: EditArtifactStore,
    composer: Composer,
    task_id: str | None,
    attempt: int,
) -> None:
    config = EditConfig.from_snapshot(edit.config)  # the stored snapshot, not current defaults
    clip = edit.clip
    if clip.status != ClipStatus.READY or not clip.storage_key:
        raise PipelineFailure("clip_not_ready", "The source clip is not ready")
    try:
        source = store.storage.path_for(clip.storage_key)
    except InvalidStorageKey:
        raise PipelineFailure("clip_missing", "The source clip file is missing") from None
    if not source.is_file():
        raise PipelineFailure("clip_missing", "The source clip file is missing")

    workspace = store.workspace(edit.id, attempt)
    captions = False
    if config.captions_enabled:
        cues = build_cues(
            _transcript_segments(edit, db),
            clip_start=clip.start_time,
            clip_end=clip.end_time,
            max_words=settings.caption_max_words,
            max_chars=settings.caption_max_chars,
        )
        edit.caption_cue_count = len(cues)
        if cues:  # no speech in this range: render without a caption layer, honestly
            store.captions_path(edit.id, attempt).write_text(
                build_ass_document(
                    cues,
                    style=config.caption_style,
                    position=config.caption_position,
                    font_family=settings.caption_font_family,
                ),
                encoding="utf-8",
            )
            captions = True
    edit.progress_percent = CAPTIONS_READY_PROGRESS
    _heartbeat(edit, db, task_id)

    composed = composer(
        source,
        store.render_path(edit.id, attempt),
        layout=config.layout,
        options=render_options_from(settings),
        workspace=workspace,
        captions=captions,
        heartbeat=lambda: _heartbeat(edit, db, task_id),
    )
    edit.progress_percent = RENDER_DONE_PROGRESS
    _heartbeat(edit, db, task_id)

    edit.status = ClipEditStatus.VALIDATING
    edit.progress_percent = VALIDATING_PROGRESS
    _heartbeat(edit, db, task_id)

    _ensure_still_owner(edit, db, task_id)
    key = store.finalize(edit.id, attempt)  # file first, then the row
    store.discard_workspace(edit.id, attempt)  # the caption file is no longer needed
    edit.storage_key = key
    edit.file_size = composed.size_bytes
    edit.duration_seconds = composed.duration_seconds
    edit.width, edit.height = composed.width, composed.height
    edit.fps = composed.fps
    edit.video_codec, edit.audio_codec = composed.video_codec, composed.audio_codec
    edit.status = ClipEditStatus.READY
    edit.progress_percent = 100
    edit.completed_at = _now()
    _heartbeat(edit, db, task_id)
    logger.info(
        "Clip edit %s ready: %s, captions %s (%s cues), %.2fs, %s bytes",
        edit.id,
        config.layout.value,
        "on" if config.captions_enabled else "off",
        edit.caption_cue_count,
        composed.duration_seconds,
        composed.size_bytes,
    )


def _transcript_segments(edit: ClipEdit, db: Session) -> list[SourceSegment]:
    transcription = edit.clip.video.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        raise PipelineFailure(
            "transcript_unavailable", "Captions need a completed transcript for this video"
        )
    rows = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_id == transcription.id)
        .order_by(TranscriptSegment.sequence_index)
    )
    return [SourceSegment(start=r.start_time, end=r.end_time, text=r.text) for r in rows]


# --- state helpers ----------------------------------------------------------------------


def _still_owner(edit: ClipEdit, db: Session, task_id: str | None) -> bool:
    if task_id is None:
        return True
    current = db.scalar(select(ClipEdit.celery_task_id).where(ClipEdit.id == edit.id))
    return not current or current == task_id


def _ensure_still_owner(edit: ClipEdit, db: Session, task_id: str | None) -> None:
    if not _still_owner(edit, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(edit: ClipEdit, db: Session, task_id: str | None = None) -> None:
    """Commit progress — but only while this attempt still owns the edit."""
    _ensure_still_owner(edit, db, task_id)
    edit.heartbeat_at = _now()
    db.commit()


def _fail(
    edit: ClipEdit,
    db: Session,
    store: EditArtifactStore,
    code: str,
    message: str,
    *,
    task_id: str | None = None,
    attempt: int = 1,
) -> None:
    db.rollback()
    if not _still_owner(edit, db, task_id):
        store.discard_workspace(edit.id, attempt)  # our own files only
        logger.info(
            "Clip edit %s failed (%s) after being taken over; newer attempt untouched",
            edit.id,
            code,
        )
        return
    store.discard(edit.id)  # no partial render, caption file or orphaned artifact survives
    edit.status = ClipEditStatus.FAILED
    edit.error_code = code[:64]
    edit.error_message = message[:MAX_ERROR_LENGTH]
    edit.storage_key = None
    edit.completed_at = _now()
    edit.heartbeat_at = edit.completed_at
    db.commit()
    logger.warning("Clip edit %s failed: %s — %s", edit.id, code, message)
