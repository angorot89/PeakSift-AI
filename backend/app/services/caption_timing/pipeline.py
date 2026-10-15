"""The caption-timing job: clip audio → word timestamps → validated, clip-local words.

Runs in a Celery worker (``peaksift.generate_caption_track``; only the track id crosses the
broker). The ``caption_tracks`` row is the source of truth:

- **Claiming:** a completed track is never re-run; a live one (fresh heartbeat) is not run
  twice; a failed one runs again only after the retry endpoint resets it; a row whose task
  id belongs to a newer attempt is ignored.
- **Ownership:** the task id committed before enqueueing is the attempt token. Every commit
  and the failure path re-read it, so a stalled worker that a retry took over never writes
  the row or its words. A row deleted mid-run (its clip was removed) stops the job.
- **Source:** the generated clip's own file (the exact artifact being edited) — never the
  original upload, never a re-transcription of the whole video. Its audio is decoded by the
  provider straight to memory (ffmpeg → PCM pipe), so no temporary audio file exists to leak
  or clean up.
- **Clip-local time:** the clip's audio starts at the clip's first frame, so provider times
  already are clip-local seconds. They are re-validated here against the clip's duration.
- **Transactional result:** words, statistics and ``completed`` are written in ONE commit; a
  failure leaves no words.
- **Honest progress:** stage-based (faster-whisper exposes no reliable per-word progress):
  5 claimed, 10 preparing audio, 20 aligning, 85 validating, 100 completed.

A clip without an audio stream has no speech: the track completes with zero words.
"""

import logging
import uuid
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import CaptionTrack, CaptionTrackStatus, CaptionWord, ClipStatus
from app.services.caption_timing.config import CaptionTimingConfig
from app.services.caption_timing.contract import (
    CaptionTimingError,
    CaptionTimingProvider,
    CaptionTimingRequest,
    TimedWord,
    require_word_timestamps,
    validate_words,
)
from app.services.caption_timing.factory import get_timing_provider
from app.services.storage import InvalidStorageKey, LocalStorageProvider

logger = logging.getLogger(__name__)

CLAIMED_PROGRESS = 5
AUDIO_PROGRESS = 10
ALIGNING_PROGRESS = 20
VALIDATING_PROGRESS = 85
MAX_ERROR_LENGTH = 500


class PipelineSuperseded(Exception):
    """A newer attempt owns this track (or the row is gone); stop without writing."""


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(track: CaptionTrack, settings: Settings, *, now: datetime | None = None) -> bool:
    active = (
        CaptionTrackStatus.PREPARING_AUDIO,
        CaptionTrackStatus.ALIGNING,
        CaptionTrackStatus.VALIDATING,
    )
    if track.status not in active:
        return False
    last = track.heartbeat_at or track.started_at or track.created_at
    return ((now or _now()) - last).total_seconds() > settings.caption_timing_stale_after_seconds


def provider_for(config: CaptionTimingConfig, settings: Settings) -> CaptionTimingProvider:
    """The provider exactly as the track's snapshot describes it (not today's defaults)."""
    pinned = settings.model_copy(
        update={
            "caption_timing_provider": config.provider,
            "faster_whisper_model": config.model,
            "faster_whisper_compute_type": config.compute_type,
            "faster_whisper_beam_size": config.beam_size,
        }
    )
    return get_timing_provider(pinned)


def run_caption_track(
    track_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: LocalStorageProvider | None = None,
    provider: CaptionTimingProvider | None = None,
    task_id: str | None = None,
) -> CaptionTrack | None:
    """Time the words of one ``CaptionTrack`` row. Problems are recorded, never raised."""
    settings = settings or get_settings()
    storage = storage or LocalStorageProvider(settings.media_root)
    track = db.get(CaptionTrack, track_id)
    if track is None:
        logger.warning("Caption track %s no longer exists; nothing to do", track_id)
        return None
    if not _claim(track, db, settings, task_id):
        return track

    def fail(code: str, message: str) -> None:
        try:
            _fail(track, db, code, message, task_id=task_id)
        except Exception:
            # The database itself is failing: leave the row to go stale; retry recovers it.
            logger.exception("Could not record the failure of caption track %s", track_id)
            db.rollback()

    try:
        _execute(track, db, settings, storage, provider, task_id)
    except PipelineSuperseded:
        logger.info("Caption track %s was taken over or removed; stopping", track_id)
    except PipelineFailure as error:
        fail(error.code, error.message)
    except CaptionTimingError as error:
        fail(error.code, error.message)
    except SoftTimeLimitExceeded:
        fail("time_limit", "Word timing ran longer than the worker allows; retry it")
    except Exception:
        logger.exception("Unexpected error timing caption track %s", track_id)
        fail("internal_error", "Unexpected error while timing the words")
    return track


# --- claiming -----------------------------------------------------------------------------


def _claim(track: CaptionTrack, db: Session, settings: Settings, task_id: str | None) -> bool:
    if task_id and track.celery_task_id and track.celery_task_id != task_id:
        logger.info("Caption track %s belongs to a newer attempt; ignoring", track.id)
        return False
    if track.status == CaptionTrackStatus.COMPLETED:
        logger.info("Caption track %s is already completed; ignoring duplicate task", track.id)
        return False
    if track.status == CaptionTrackStatus.FAILED:
        logger.info("Caption track %s is failed; a retry must reset it first", track.id)
        return False
    if track.status != CaptionTrackStatus.QUEUED and not is_stale(track, settings):
        logger.info("Caption track %s is already running elsewhere", track.id)
        return False
    now = _now()
    db.execute(delete(CaptionWord).where(CaptionWord.caption_track_id == track.id))
    track.status = CaptionTrackStatus.PREPARING_AUDIO
    track.progress_percent = CLAIMED_PROGRESS
    track.started_at = track.heartbeat_at = now
    track.completed_at = None
    track.error_code = track.error_message = None
    track.language = track.language_probability = track.audio_duration_seconds = None
    track.word_count = track.rejected_word_count = track.average_confidence = None
    db.commit()
    return True


# --- the work -------------------------------------------------------------------------------


def _execute(
    track: CaptionTrack,
    db: Session,
    settings: Settings,
    storage: LocalStorageProvider,
    provider: CaptionTimingProvider | None,
    task_id: str | None,
) -> None:
    try:
        config = CaptionTimingConfig.from_snapshot(track.config)  # the stored snapshot
    except ValueError:
        raise PipelineFailure(
            "config_invalid", "The caption timing configuration is not supported"
        ) from None
    clip = track.clip
    if clip.status != ClipStatus.READY or not clip.storage_key:
        raise PipelineFailure("clip_not_ready", "The source clip is not ready")
    try:
        source = storage.path_for(clip.storage_key)
    except InvalidStorageKey:
        raise PipelineFailure("clip_missing", "The source clip file is missing") from None
    if not source.is_file():
        raise PipelineFailure("clip_missing", "The source clip file is missing")
    track.progress_percent = AUDIO_PROGRESS
    _heartbeat(track, db, task_id)

    duration = float(clip.duration_seconds)
    if not clip.audio_codec:  # no audio stream: no speech to time, honestly zero words
        _ensure_still_owner(track, db, task_id)
        _finalize(track, db, (), rejected=0, language=None, probability=None, audio_duration=0.0)
        _heartbeat(track, db, task_id)
        return

    timing = provider or provider_for(config, settings)
    require_word_timestamps(timing)
    track.status = CaptionTrackStatus.ALIGNING
    track.progress_percent = ALIGNING_PROGRESS
    _heartbeat(track, db, task_id)
    result = timing.time_words(CaptionTimingRequest(source, config.language_hint))

    track.status = CaptionTrackStatus.VALIDATING
    track.progress_percent = VALIDATING_PROGRESS
    _heartbeat(track, db, task_id)
    words, rejected = clip_local_words(result.words, duration)

    _ensure_still_owner(track, db, task_id)
    _finalize(
        track,
        db,
        words,
        rejected=result.rejected_words + rejected,
        language=result.language,
        probability=result.language_probability,
        audio_duration=result.audio_duration,
    )
    _heartbeat(track, db, task_id)
    logger.info(
        "Caption track %s completed: %d words (%d rejected), language %s",
        track.id,
        len(words),
        track.rejected_word_count,
        track.language,
    )


def clip_local_words(
    words: tuple[TimedWord, ...], clip_duration: float
) -> tuple[tuple[TimedWord, ...], int]:
    """Re-validate provider words against the clip itself. The decoded audio can run a little
    past the last video frame: a word starting after the clip's end is dropped (and counted),
    an end past it is clamped. The result passes the strict contract check with no tolerance.
    """
    inside: list[TimedWord] = []
    dropped = 0
    for w in words:
        if w.start >= clip_duration:
            dropped += 1
            continue
        inside.append(TimedWord(w.start, min(w.end, clip_duration), w.text, w.confidence))
    checked, rejected = validate_words(inside, audio_duration=clip_duration, tolerance=0.0)
    return checked, dropped + rejected


def _finalize(
    track: CaptionTrack,
    db: Session,
    words: tuple[TimedWord, ...],
    *,
    rejected: int,
    language: str | None,
    probability: float | None,
    audio_duration: float,
) -> None:
    db.execute(delete(CaptionWord).where(CaptionWord.caption_track_id == track.id))
    db.add_all(
        CaptionWord(
            caption_track_id=track.id,
            sequence_index=index,
            start_time=w.start,
            end_time=w.end,
            text=w.text,
            confidence=w.confidence,
        )
        for index, w in enumerate(words)
    )
    known = [w.confidence for w in words if w.confidence is not None]
    track.word_count = len(words)
    track.rejected_word_count = rejected
    track.average_confidence = round(sum(known) / len(known), 4) if known else None
    track.language = language[:16] if language else None
    track.language_probability = (
        None if probability is None else round(min(1.0, max(0.0, float(probability))), 4)
    )
    track.audio_duration_seconds = round(max(0.0, audio_duration), 3)
    track.status = CaptionTrackStatus.COMPLETED
    track.progress_percent = 100
    track.completed_at = _now()


# --- state helpers ----------------------------------------------------------------------------


def _key(track: CaptionTrack) -> uuid.UUID:
    """The primary key without a database round trip (safe if the row was deleted)."""
    return sa_inspect(track).identity[0]


def _still_owner(track: CaptionTrack, db: Session, task_id: str | None) -> bool:
    with db.no_autoflush:  # read the committed token; never flush pending progress first
        row = db.execute(
            select(CaptionTrack.celery_task_id).where(CaptionTrack.id == _key(track))
        ).first()
    if row is None:
        return False
    if task_id is None:
        return True
    return not row.celery_task_id or row.celery_task_id == task_id


def _ensure_still_owner(track: CaptionTrack, db: Session, task_id: str | None) -> None:
    if not _still_owner(track, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(track: CaptionTrack, db: Session, task_id: str | None = None) -> None:
    """Commit progress — but only while this attempt still owns the track."""
    _ensure_still_owner(track, db, task_id)
    track.heartbeat_at = _now()
    db.commit()


def _fail(
    track: CaptionTrack, db: Session, code: str, message: str, *, task_id: str | None = None
) -> None:
    db.rollback()
    track_id = _key(track)
    if not _still_owner(track, db, task_id):
        logger.info("Caption track %s failed (%s) after being taken over; ignoring", track_id, code)
        return
    db.execute(delete(CaptionWord).where(CaptionWord.caption_track_id == track_id))
    track.status = CaptionTrackStatus.FAILED
    track.error_code = code[:64]
    track.error_message = message[:MAX_ERROR_LENGTH]
    track.completed_at = _now()
    track.heartbeat_at = track.completed_at
    db.commit()
    logger.warning("Caption track %s failed: %s — %s", track_id, code, message)
