"""The transcription job: video → normalized audio → chunks → provider → absolute segments.

Runs inside a Celery worker. The database row is the source of truth and the guard
against duplicate delivery: a completed job is never redone, a live job (fresh
heartbeat) is never started twice, and a retry starts from a clean slate.

Progress is real: 0 while queued, 5 once audio is ready, then 5 + 95 × chunks done /
chunks total, 100 on completion. It never moves backwards during a run.

Attempt ownership: the Celery task id committed on the row (before the job is enqueued) is
the fencing token. Every commit and the failure path re-read it; a worker whose attempt was
superseded by a retry stops without writing — it cannot overwrite progress, mark the newer
attempt failed or completed, or delete its segments. Each attempt also works in its own
``transcription/<id>/<attempt>/`` directory, so it never touches another attempt's files.
"""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Transcription, TranscriptionStatus, TranscriptSegment, VideoStatus
from app.services.audio_extraction import (
    AudioExtractionError,
    extract_normalized_audio,
    normalized_audio_key,
)
from app.services.media_timing import MediaTimingError, fit_to_media, media_duration
from app.services.storage import LocalMediaStorage
from app.services.transcription.chunking import (
    AudioChunk,
    ChunkingError,
    attempt_workspace,
    cleanup_chunks,
    cleanup_other_workspaces,
    shift_segments,
    split_audio,
)
from app.services.transcription.contract import (
    ProviderOutputError,
    ProviderSegment,
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionRequest,
    validate_segments,
)
from app.services.transcription.factory import get_transcription_provider

logger = logging.getLogger(__name__)

AUDIO_READY_PROGRESS = 5
MAX_ERROR_LENGTH = 500

ProviderFactory = Callable[[Settings], TranscriptionProvider]


class PipelineSuperseded(Exception):
    """Another task now owns this transcription (retry/stale restart); stop without writing."""


class PipelineFailure(Exception):
    """A job cannot continue. Recorded on the row with a stable code and safe message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(
    transcription: Transcription, settings: Settings, *, now: datetime | None = None
) -> bool:
    """An active job whose worker stopped reporting for longer than the stale threshold."""
    if transcription.status not in (
        TranscriptionStatus.EXTRACTING_AUDIO,
        TranscriptionStatus.TRANSCRIBING,
    ):
        return False
    last = transcription.heartbeat_at or transcription.started_at or transcription.created_at
    age = ((now or _now()) - last).total_seconds()
    return age > settings.transcription_stale_after_seconds


def run_transcription(
    transcription_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: LocalMediaStorage | None = None,
    provider_factory: ProviderFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
    task_id: str | None = None,
) -> Transcription | None:
    """Execute the job for a `Transcription` row. Never raises for a bad file or provider.

    ``task_id`` is the Celery task id that was enqueued for this row. It acts as a fencing
    token: if the row has since been handed to a newer task (retry or stale restart), this
    run stops at the next checkpoint without touching the row.
    """
    settings = settings or get_settings()
    storage = storage or LocalMediaStorage(settings.media_root)
    provider_factory = provider_factory or get_transcription_provider  # resolved at call time

    transcription = db.get(Transcription, transcription_id)
    if transcription is None:
        logger.warning("Transcription %s no longer exists; nothing to do", transcription_id)
        return None
    if not _claim(transcription, db, settings, task_id):
        return transcription
    workspace = attempt_workspace(transcription.id, task_id)
    # Files of earlier attempts are derived data; a stalled worker still reading them only
    # fails its own (fenced) run.
    cleanup_other_workspaces(storage, transcription.id, keep=workspace)

    def fail(code: str, message: str) -> None:
        _fail(transcription, db, code, message, task_id=task_id)

    try:
        _execute(transcription, db, settings, storage, provider_factory, sleep, task_id, workspace)
    except PipelineSuperseded:
        logger.info("Transcription %s was taken over by a newer task; stopping", transcription.id)
    except PipelineFailure as failure:
        fail(failure.code, failure.message)
    except (AudioExtractionError, ChunkingError) as error:
        fail(error.code, error.message)
    except TranscriptionProviderError as error:
        fail(error.code, error.message)
    except Exception:
        logger.exception("Unexpected error transcribing %s", transcription.id)
        fail("internal_error", "Unexpected error during transcription")
    finally:
        cleanup_chunks(storage, workspace)  # always this attempt's own chunks only
    return transcription


# --- claiming -----------------------------------------------------------------------


def _claim(
    transcription: Transcription, db: Session, settings: Settings, task_id: str | None
) -> bool:
    """Move a runnable job to extracting_audio; return False for anything not runnable."""
    if task_id and transcription.celery_task_id and transcription.celery_task_id != task_id:
        logger.info("Transcription %s belongs to a newer task; ignoring", transcription.id)
        return False
    if transcription.status == TranscriptionStatus.COMPLETED:
        logger.info("Transcription %s already completed; ignoring duplicate task", transcription.id)
        return False
    if transcription.status == TranscriptionStatus.FAILED:
        logger.info("Transcription %s is failed; a retry must reset it first", transcription.id)
        return False
    if transcription.status != TranscriptionStatus.QUEUED and not is_stale(transcription, settings):
        logger.info("Transcription %s is already running elsewhere", transcription.id)
        return False

    now = _now()
    transcription.status = TranscriptionStatus.EXTRACTING_AUDIO
    transcription.started_at = now
    transcription.heartbeat_at = now
    transcription.completed_at = None
    transcription.progress_percent = 0
    transcription.error_code = None
    transcription.error_message = None
    transcription.full_text = None
    transcription.language = None
    transcription.language_probability = None
    # A retry (or a stale restart) starts clean: no segments from an earlier attempt.
    db.execute(
        delete(TranscriptSegment).where(TranscriptSegment.transcription_id == transcription.id)
    )
    db.commit()
    return True


# --- the work -------------------------------------------------------------------------


def _execute(
    transcription: Transcription,
    db: Session,
    settings: Settings,
    storage: LocalMediaStorage,
    provider_factory: ProviderFactory,
    sleep: Callable[[float], None],
    task_id: str | None,
    workspace: str,
) -> None:
    video = transcription.video
    if video.status != VideoStatus.READY:
        raise PipelineFailure("video_not_ready", "The video is not ready for transcription")
    source = storage.path_for(video.storage_key)
    if not source.is_file():
        raise PipelineFailure("video_unavailable", "The source video file is missing")

    audio = extract_normalized_audio(
        source,
        storage,
        normalized_audio_key(workspace),
        ffmpeg_path=settings.ffmpeg_path,
        ffprobe_path=settings.ffprobe_path,
        timeout_seconds=settings.audio_extraction_timeout_seconds,
    )
    if not audio.duration_seconds:
        raise PipelineFailure("audio_unreadable", "The extracted audio has no readable duration")
    transcription.audio_storage_key = audio.storage_key
    transcription.audio_duration_seconds = audio.duration_seconds
    # Persisted segments must lie inside the media: the shorter of the video and its audio.
    duration = media_duration(video.duration_seconds, audio.duration_seconds)
    transcription.progress_percent = AUDIO_READY_PROGRESS
    _heartbeat(transcription, db, task_id)

    chunks = split_audio(
        storage.path_for(audio.storage_key),
        storage,
        workspace,
        total_seconds=audio.duration_seconds,
        chunk_seconds=settings.transcription_chunk_seconds,
        ffmpeg_path=settings.ffmpeg_path,
        ffprobe_path=settings.ffprobe_path,
        timeout_seconds=settings.audio_extraction_timeout_seconds,
    )
    transcription.status = TranscriptionStatus.TRANSCRIBING
    _heartbeat(transcription, db, task_id)

    provider = provider_factory(settings)
    transcription.provider = provider.name
    transcription.model = provider.model

    sequence = 0
    previous_tail: str | None = None
    for position, chunk in enumerate(chunks, start=1):
        result = _transcribe_with_retry(
            provider,
            TranscriptionRequest(
                audio_path=storage.path_for(chunk.storage_key),
                language_hint=transcription.language,
                prompt=previous_tail,
            ),
            settings,
            sleep,
        )
        _heartbeat(transcription, db, commit=False)
        segments = _fit_to_media(
            _absolute_segments(result.segments, chunk, settings), duration, settings
        )
        for segment in segments:
            db.add(
                TranscriptSegment(
                    transcription_id=transcription.id,
                    sequence_index=sequence,
                    start_time=segment.start,
                    end_time=segment.end,
                    text=segment.text,
                    speaker=segment.speaker,
                )
            )
            sequence += 1
        if transcription.language is None and result.language:
            transcription.language = result.language
            transcription.language_probability = result.language_probability
        transcription.progress_percent = max(
            transcription.progress_percent,
            AUDIO_READY_PROGRESS + int((100 - AUDIO_READY_PROGRESS) * position / len(chunks)),
        )
        _heartbeat(transcription, db, task_id)  # one transaction per chunk (ownership checked)
        if settings.transcription_prompt_tail_chars and result.text:
            previous_tail = result.text[-settings.transcription_prompt_tail_chars :]

    _ensure_still_owner(transcription, db, task_id)
    db.refresh(transcription, attribute_names=["segments"])
    transcription.full_text = " ".join(s.text for s in transcription.segments)
    transcription.status = TranscriptionStatus.COMPLETED
    transcription.progress_percent = 100
    transcription.completed_at = _now()
    _heartbeat(transcription, db, task_id)
    logger.info(
        "Transcription %s completed: %s segments, %s chunks",
        transcription.id,
        sequence,
        len(chunks),
    )


def _fit_to_media(
    segments: tuple[ProviderSegment, ...], duration: float | None, settings: Settings
) -> tuple[ProviderSegment, ...]:
    """Normalize a small overshoot past the media's end; refuse anything worse."""
    fitted = []
    for segment in segments:
        try:
            start, end = fit_to_media(
                segment.start,
                segment.end,
                duration,
                tolerance=settings.transcription_timestamp_tolerance_seconds,
            )
        except MediaTimingError as error:
            raise ProviderOutputError(str(error)) from None
        fitted.append(
            ProviderSegment(start=start, end=end, text=segment.text, speaker=segment.speaker)
        )
    return tuple(fitted)


def _absolute_segments(
    segments: tuple[ProviderSegment, ...], chunk: AudioChunk, settings: Settings
) -> tuple[ProviderSegment, ...]:
    """Shift chunk-relative times by the chunk start and refuse times beyond the chunk."""
    segments = validate_segments(segments)  # defence in depth: never trust a provider blindly
    limit = chunk.duration_seconds + settings.transcription_timestamp_tolerance_seconds
    for segment in segments:
        if segment.end > limit:
            raise ProviderOutputError(
                f"A segment ends at {segment.end:.2f}s, beyond the "
                f"{chunk.duration_seconds:.2f}s chunk"
            )
    return shift_segments(segments, chunk.start_seconds)


def _transcribe_with_retry(
    provider: TranscriptionProvider,
    request: TranscriptionRequest,
    settings: Settings,
    sleep: Callable[[float], None],
):
    """Bounded exponential backoff for transient provider errors only."""
    attempts = settings.transcription_provider_max_attempts
    for attempt in range(1, attempts + 1):
        try:
            return provider.transcribe(request)
        except TranscriptionProviderError as error:
            if not error.retryable or attempt == attempts:
                raise
            delay = settings.transcription_retry_backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Provider error %s on attempt %s/%s; retrying in %.1fs",
                error.code,
                attempt,
                attempts,
                delay,
            )
            sleep(delay)
    raise AssertionError("unreachable")


# --- state helpers ----------------------------------------------------------------------


def _still_owner(transcription: Transcription, db: Session, task_id: str | None) -> bool:
    """Read the token straight from the database (not the identity map)."""
    if task_id is None:
        return True
    current = db.scalar(
        select(Transcription.celery_task_id).where(Transcription.id == transcription.id)
    )
    return not current or current == task_id


def _ensure_still_owner(transcription: Transcription, db: Session, task_id: str | None) -> None:
    """A newer task id means this run must stop writing."""
    if not _still_owner(transcription, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(
    transcription: Transcription,
    db: Session,
    task_id: str | None = None,
    *,
    commit: bool = True,
) -> None:
    transcription.heartbeat_at = _now()
    if commit:
        _ensure_still_owner(transcription, db, task_id)  # never commit for a newer attempt
        db.commit()


def _fail(
    transcription: Transcription,
    db: Session,
    code: str,
    message: str,
    *,
    task_id: str | None = None,
) -> None:
    db.rollback()  # discard anything uncommitted from the failed step
    if not _still_owner(transcription, db, task_id):
        logger.info(
            "Transcription %s failed (%s) after being taken over; newer attempt untouched",
            transcription.id,
            code,
        )
        return
    transcription.status = TranscriptionStatus.FAILED
    transcription.error_code = code[:64]
    transcription.error_message = message[:MAX_ERROR_LENGTH]
    transcription.completed_at = _now()
    transcription.heartbeat_at = transcription.completed_at
    # A failed transcription keeps no partial transcript; a retry starts clean anyway.
    db.execute(
        delete(TranscriptSegment).where(TranscriptSegment.transcription_id == transcription.id)
    )
    db.commit()
    logger.warning("Transcription %s failed: %s — %s", transcription.id, code, message)
