"""The clip render job: Clip row → FFmpeg → validated temp file → atomic finalize → ready.

Runs inside a Celery worker. The ``clips`` row is the source of truth and the guard
against duplicate delivery: a ready clip is never re-rendered, a live clip (fresh
heartbeat) is never rendered twice, a failed clip only re-runs after the retry endpoint
resets it, and the Celery task id on the row is a fencing token re-checked before the
final commit.

Order of operations makes ``ready`` mean "a validated artifact exists at storage_key":
render to the temp name → ffprobe validation (inside the renderer) → ``os.replace`` to the
final name → one commit that sets storage_key, metadata and ``ready``. If that commit
fails, the row is not ready and a retry discards the orphaned file first.

Progress is honest stage progress: 0 queued, 10 render started, 80 render finished,
90 validating/finalizing, 100 ready. Heartbeats are written while FFmpeg runs.

Fencing: once claimed, every commit first re-reads the task id on the row. A worker that a
retry has taken over (a stalled-but-alive "zombie") stops at its next heartbeat — FFmpeg is
killed — and never writes the row or touches the new attempt's files; each attempt renders
into its own temp file.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Clip, ClipStatus, VideoStatus
from app.services.clip_render.renderer import (
    RenderedClip,
    RenderError,
    RenderOptions,
    render_clip,
)
from app.services.clip_render.storage import ClipArtifactStore, StorageError
from app.services.storage import LocalMediaStorage

logger = logging.getLogger(__name__)

RENDER_STARTED_PROGRESS = 10
RENDER_DONE_PROGRESS = 80
VALIDATING_PROGRESS = 90
MAX_ERROR_LENGTH = 500

Renderer = Callable[..., RenderedClip]


class PipelineSuperseded(Exception):
    """Another task now owns this clip (retry/stale restart); stop without writing."""


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def render_options_from(settings: Settings) -> RenderOptions:
    return RenderOptions(
        ffmpeg_path=settings.ffmpeg_path,
        ffprobe_path=settings.ffprobe_path,
        preset=settings.clip_render_preset,
        crf=settings.clip_render_crf,
        audio_bitrate=settings.clip_audio_bitrate,
        timeout_seconds=settings.clip_render_timeout_seconds,
        duration_tolerance_seconds=settings.clip_render_duration_tolerance_seconds,
        source_tolerance_seconds=settings.clip_render_source_tolerance_seconds,
        heartbeat_interval_seconds=settings.clip_render_heartbeat_seconds,
    )


def is_stale(clip: Clip, settings: Settings, *, now: datetime | None = None) -> bool:
    """A rendering job whose worker stopped reporting for longer than the stale threshold."""
    if clip.status not in (ClipStatus.RENDERING, ClipStatus.VALIDATING):
        return False
    last = clip.heartbeat_at or clip.started_at or clip.created_at
    return ((now or _now()) - last).total_seconds() > settings.clip_render_stale_after_seconds


def run_clip_render(
    clip_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: LocalMediaStorage | None = None,
    renderer: Renderer = render_clip,
    task_id: str | None = None,
) -> Clip | None:
    """Execute the render for a ``Clip`` row. Problems are recorded on the row, never raised."""
    settings = settings or get_settings()
    store = ClipArtifactStore(storage or LocalMediaStorage(settings.media_root))

    clip = db.get(Clip, clip_id)
    if clip is None:
        logger.warning("Clip %s no longer exists; nothing to render", clip_id)
        return None
    if not _claim(clip, db, settings, store, task_id):
        return clip
    attempt = clip.attempt  # this run's temp file; fixed for the whole run

    def fail(code: str, message: str) -> None:
        _fail(clip, db, store, code, message, task_id=task_id, attempt=attempt)

    try:
        _execute(clip, db, settings, store, renderer, task_id, attempt)
    except PipelineSuperseded:
        store.discard_temp(clip.id, attempt)
        logger.info("Clip %s was taken over by a newer task; stopping", clip.id)
    except (PipelineFailure, RenderError) as error:
        fail(error.code, error.message)
    except StorageError:
        logger.exception("Storage failure while finalizing clip %s", clip.id)
        fail("storage_failure", "The rendered clip could not be stored")
    except SoftTimeLimitExceeded:
        fail(
            "time_limit",
            "Rendering ran longer than the worker allows; retry or choose a shorter clip",
        )
    except Exception:
        logger.exception("Unexpected error rendering clip %s", clip.id)
        fail("internal_error", "Unexpected error while rendering the clip")
    return clip


# --- claiming -----------------------------------------------------------------------


def _claim(
    clip: Clip, db: Session, settings: Settings, store: ClipArtifactStore, task_id: str | None
) -> bool:
    if task_id and clip.celery_task_id and clip.celery_task_id != task_id:
        logger.info("Clip %s belongs to a newer task; ignoring", clip.id)
        return False
    if clip.status == ClipStatus.READY:
        logger.info("Clip %s is already ready; ignoring duplicate task", clip.id)
        return False
    if clip.status == ClipStatus.FAILED:
        logger.info("Clip %s is failed; a retry must reset it first", clip.id)
        return False
    if clip.status != ClipStatus.QUEUED and not is_stale(clip, settings):
        logger.info("Clip %s is already rendering elsewhere", clip.id)
        return False

    # Nothing from an earlier attempt may survive: no stale temp, no orphaned final file.
    store.discard(clip.id)
    now = _now()
    clip.status = ClipStatus.RENDERING
    clip.started_at = now
    clip.heartbeat_at = now
    clip.completed_at = None
    clip.progress_percent = RENDER_STARTED_PROGRESS
    clip.error_code = None
    clip.error_message = None
    clip.storage_key = None
    clip.file_size = None
    clip.width = clip.height = None
    clip.fps = None
    clip.video_codec = clip.audio_codec = None
    db.commit()
    return True


# --- the work -------------------------------------------------------------------------


def _execute(
    clip: Clip,
    db: Session,
    settings: Settings,
    store: ClipArtifactStore,
    renderer: Renderer,
    task_id: str | None,
    attempt: int,
) -> None:
    video = clip.video
    if video.status != VideoStatus.READY:
        raise PipelineFailure("video_not_ready", "The source video is not ready")
    source: Path = store.storage.path_for(video.storage_key)
    if not source.is_file():
        raise PipelineFailure("source_missing", "The source video file is missing")

    rendered = renderer(
        source,
        store.temp_path(clip.id, attempt),
        start=clip.start_time,
        end=clip.end_time,
        options=render_options_from(settings),
        heartbeat=lambda: _heartbeat(clip, db, task_id),
    )
    clip.progress_percent = RENDER_DONE_PROGRESS
    _heartbeat(clip, db, task_id)

    clip.status = ClipStatus.VALIDATING
    clip.progress_percent = VALIDATING_PROGRESS
    _heartbeat(clip, db, task_id)

    _ensure_still_owner(clip, db, task_id)
    # File first, then the row: "ready" can only ever point at a finalized, validated file.
    key = store.finalize(clip.id, attempt)
    clip.storage_key = key
    clip.file_size = rendered.size_bytes
    clip.width, clip.height = rendered.width, rendered.height
    clip.fps = rendered.fps
    clip.video_codec, clip.audio_codec = rendered.video_codec, rendered.audio_codec
    clip.status = ClipStatus.READY
    clip.progress_percent = 100
    clip.completed_at = _now()
    _heartbeat(clip, db, task_id)
    logger.info(
        "Clip %s ready: %.2fs, %sx%s, %s bytes",
        clip.id,
        rendered.duration_seconds,
        rendered.width,
        rendered.height,
        rendered.size_bytes,
    )


# --- state helpers ----------------------------------------------------------------------


def _still_owner(clip: Clip, db: Session, task_id: str | None) -> bool:
    if task_id is None:
        return True
    current = db.scalar(select(Clip.celery_task_id).where(Clip.id == clip.id))
    return not current or current == task_id


def _ensure_still_owner(clip: Clip, db: Session, task_id: str | None) -> None:
    if not _still_owner(clip, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(clip: Clip, db: Session, task_id: str | None = None) -> None:
    """Commit progress/heartbeat — but only while this task still owns the row."""
    _ensure_still_owner(clip, db, task_id)
    clip.heartbeat_at = _now()
    db.commit()


def _fail(
    clip: Clip,
    db: Session,
    store: ClipArtifactStore,
    code: str,
    message: str,
    *,
    task_id: str | None = None,
    attempt: int = 1,
) -> None:
    db.rollback()
    if not _still_owner(clip, db, task_id):
        # A newer attempt owns the row and its files: clean up only our own temp output.
        store.discard_temp(clip.id, attempt)
        logger.info(
            "Clip %s failed after being taken over (%s); newer attempt untouched", clip.id, code
        )
        return
    store.discard(clip.id)  # no partial or orphaned artifact survives a failure
    clip.status = ClipStatus.FAILED
    clip.error_code = code[:64]
    clip.error_message = message[:MAX_ERROR_LENGTH]
    clip.storage_key = None
    clip.completed_at = _now()
    clip.heartbeat_at = clip.completed_at
    db.commit()
    logger.warning("Clip %s failed: %s — %s", clip.id, code, message)
