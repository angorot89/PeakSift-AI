"""The clip detection job: transcript snapshot → windows → provider → validation → ranking.

Runs inside a Celery worker. The ``clip_detection_runs`` row is the source of truth and
the guard against duplicate delivery: a completed run is never redone, a live run
(fresh heartbeat) is never started twice, a failed run only re-runs after the retry
endpoint resets it, and the Celery task id on the row is a fencing token re-checked
before every commit.

Progress is real and monotonic: 0 queued, 5 once the transcript is prepared, then
5 + 75 × windows done / windows total while analysing, 85 validating, 90 ranking, 100
completed. Candidates are written in one transaction together with the ``completed``
status, so a run is never ``completed`` with a partial result set.
"""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    ClipCandidate,
    ClipDetectionRun,
    ClipDetectionStatus,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.services.clip_detection.contract import (
    AnalysisWindow,
    ClipAnalysisProvider,
    ClipAnalysisRequest,
    ClipAnalysisResult,
    ClipProviderError,
    TranscriptLine,
)
from app.services.clip_detection.detection_config import DetectionConfig
from app.services.clip_detection.factory import get_clip_provider
from app.services.clip_detection.ranking import rank_candidates
from app.services.clip_detection.validation import ValidatedCandidate, validate_candidates
from app.services.clip_detection.windowing import (
    TranscriptError,
    build_windows,
    prepare_lines,
    transcript_fingerprint,
)

logger = logging.getLogger(__name__)

PREPARED_PROGRESS = 5
ANALYZING_SPAN = 75  # 5 → 80 while windows are analysed
VALIDATING_PROGRESS = 85
RANKING_PROGRESS = 90
MAX_ERROR_LENGTH = 500

ProviderFactory = Callable[[str, str, Settings], ClipAnalysisProvider]


class PipelineSuperseded(Exception):
    """Another task now owns this run (retry/stale restart); stop without writing."""


class PipelineFailure(Exception):
    """The run cannot continue. Recorded on the row with a stable code and safe message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(run: ClipDetectionRun, settings: Settings, *, now: datetime | None = None) -> bool:
    """A running job whose worker stopped reporting for longer than the stale threshold."""
    if run.status not in (
        ClipDetectionStatus.PREPARING_TRANSCRIPT,
        ClipDetectionStatus.ANALYZING,
        ClipDetectionStatus.VALIDATING,
        ClipDetectionStatus.RANKING,
    ):
        return False
    last = run.heartbeat_at or run.started_at or run.created_at
    return ((now or _now()) - last).total_seconds() > settings.clip_detection_stale_after_seconds


def _default_provider_factory(provider: str, model: str, settings: Settings):
    return get_clip_provider(provider, model, settings)


def run_clip_detection(
    run_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    provider_factory: ProviderFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
    task_id: str | None = None,
) -> ClipDetectionRun | None:
    """Execute the job for a ``ClipDetectionRun`` row. Never raises for provider or data
    problems; those are recorded on the row."""
    settings = settings or get_settings()
    provider_factory = provider_factory or _default_provider_factory  # resolved at call time

    run = db.get(ClipDetectionRun, run_id)
    if run is None:
        logger.warning("Clip detection run %s no longer exists; nothing to do", run_id)
        return None
    if not _claim(run, db, settings, task_id):
        return run

    try:
        _execute(run, db, settings, provider_factory, sleep, task_id)
    except PipelineSuperseded:
        logger.info("Clip detection %s was taken over by a newer task; stopping", run.id)
    except (PipelineFailure, TranscriptError, ClipProviderError) as error:
        _fail(run, db, error.code, error.message, task_id=task_id)
    except SoftTimeLimitExceeded:
        # Celery's soft limit: record an honest, retryable-by-the-user failure instead of a
        # generic one, and leave the row consistent before the hard limit kills the process.
        _fail(
            run,
            db,
            "time_limit",
            "The detection ran longer than the worker allows; retry with a faster model "
            "or a smaller transcript",
            task_id=task_id,
        )
    except Exception:
        logger.exception("Unexpected error detecting clips for run %s", run.id)
        _fail(run, db, "internal_error", "Unexpected error during clip detection", task_id=task_id)
    return run


# --- claiming -----------------------------------------------------------------------


def _claim(run: ClipDetectionRun, db: Session, settings: Settings, task_id: str | None) -> bool:
    if task_id and run.celery_task_id and run.celery_task_id != task_id:
        logger.info("Run %s belongs to a newer task; ignoring", run.id)
        return False
    if run.status == ClipDetectionStatus.COMPLETED:
        logger.info("Run %s already completed; ignoring duplicate task", run.id)
        return False
    if run.status == ClipDetectionStatus.FAILED:
        logger.info("Run %s is failed; a retry must reset it first", run.id)
        return False
    if run.status != ClipDetectionStatus.QUEUED and not is_stale(run, settings):
        logger.info("Run %s is already running elsewhere", run.id)
        return False

    now = _now()
    run.status = ClipDetectionStatus.PREPARING_TRANSCRIPT
    run.started_at = now
    run.heartbeat_at = now
    run.completed_at = None
    run.progress_percent = 0
    run.windows_total = None
    run.windows_done = 0
    run.error_code = None
    run.error_message = None
    # A retry (or stale restart) starts clean: no candidates from an earlier attempt.
    db.execute(delete(ClipCandidate).where(ClipCandidate.run_id == run.id))
    db.commit()
    return True


# --- the work -------------------------------------------------------------------------


def _execute(
    run: ClipDetectionRun,
    db: Session,
    settings: Settings,
    provider_factory: ProviderFactory,
    sleep: Callable[[float], None],
    task_id: str | None,
) -> None:
    config = DetectionConfig.from_run(run.config, settings)
    lines = _load_transcript(run, db, config)
    windows = build_windows(
        lines,
        window_seconds=config.window_seconds,
        overlap_seconds=config.window_overlap_seconds,
        max_chars=config.window_max_chars,
        max_windows=config.max_windows,
    )
    run.windows_total = len(windows)
    run.progress_percent = PREPARED_PROGRESS
    run.status = ClipDetectionStatus.ANALYZING
    _heartbeat(run, db, task_id)

    provider = provider_factory(run.provider, run.model, settings)
    video_duration = float(run.video.duration_seconds or 0.0)
    language = run.transcription.language
    accepted: list[ValidatedCandidate] = []
    rejected = 0
    for position, window in enumerate(windows, start=1):
        result = _analyze_with_retry(
            provider, _request(window, video_duration, config, language), settings, sleep
        )
        report = validate_candidates(
            result.candidates,
            window=window,
            video_duration=video_duration,
            min_clip_seconds=config.min_clip_seconds,
            max_clip_seconds=config.max_clip_seconds,
            tolerance_seconds=config.timestamp_tolerance_seconds,
        )
        accepted.extend(report.accepted)
        rejected += len(report.rejected)
        for rejection in report.rejected:
            logger.info(
                "Run %s window %s: rejected proposal (%s)", run.id, window.index, rejection.reason
            )
        run.windows_done = position
        run.progress_percent = max(
            run.progress_percent,
            PREPARED_PROGRESS + int(ANALYZING_SPAN * position / len(windows)),
        )
        _heartbeat(run, db, task_id)  # one transaction per window (ownership checked)

    run.status = ClipDetectionStatus.VALIDATING
    run.progress_percent = VALIDATING_PROGRESS
    _heartbeat(run, db, task_id)
    # The transcript must still be the snapshot this run was started from.
    if transcript_fingerprint(run.transcription_id, _load_transcript(run, db, config)) != (
        run.transcript_fingerprint
    ):
        raise PipelineFailure(
            "transcript_changed",
            "The transcript changed while clips were being detected; start a new detection",
        )

    run.status = ClipDetectionStatus.RANKING
    run.progress_percent = RANKING_PROGRESS
    _heartbeat(run, db, task_id)
    ranked = rank_candidates(
        accepted, overlap_threshold=config.overlap_threshold, limit=config.target_candidates
    )

    _ensure_still_owner(run, db, task_id)
    # One transaction: every candidate row plus the completed status, or nothing.
    db.execute(delete(ClipCandidate).where(ClipCandidate.run_id == run.id))
    for item in ranked:
        candidate = item.candidate
        db.add(
            ClipCandidate(
                run_id=run.id,
                video_id=run.video_id,
                start_time=candidate.start,
                end_time=candidate.end,
                duration_seconds=candidate.end - candidate.start,
                title=candidate.title,
                hook=candidate.hook,
                rationale=candidate.rationale,
                category=candidate.category,
                transcript_excerpt=candidate.transcript_excerpt,
                overall_score=item.overall_score,
                hook_score=candidate.hook_score,
                entertainment_score=candidate.entertainment_score,
                clarity_score=candidate.clarity_score,
                payoff_score=candidate.payoff_score,
                completeness_score=candidate.completeness_score,
                rank=item.rank,
            )
        )
    run.status = ClipDetectionStatus.COMPLETED
    run.progress_percent = 100
    run.completed_at = _now()
    _heartbeat(run, db, task_id)
    logger.info(
        "Clip detection %s completed: %s candidates kept from %s accepted (%s rejected) "
        "across %s windows",
        run.id,
        len(ranked),
        len(accepted),
        rejected,
        len(windows),
    )


def _load_transcript(
    run: ClipDetectionRun, db: Session, config: DetectionConfig
) -> tuple[TranscriptLine, ...]:
    transcription = run.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        raise PipelineFailure("transcript_not_ready", "The transcript is not complete")
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_id == transcription.id)
        .order_by(TranscriptSegment.sequence_index)
    )
    return prepare_lines(
        (TranscriptLine(start=s.start_time, end=s.end_time, text=s.text) for s in segments),
        video_duration=float(run.video.duration_seconds or 0.0),
        # Transcript lines follow the transcript's own media-bounds rule (media_timing.py);
        # the snapshot's tolerance is for snapping model-proposed times.
        tolerance_seconds=get_settings().transcription_timestamp_tolerance_seconds,
    )


def _request(
    window: AnalysisWindow, video_duration: float, config: DetectionConfig, language: str | None
) -> ClipAnalysisRequest:
    return ClipAnalysisRequest(
        window=window,
        video_duration=video_duration,
        min_clip_seconds=config.min_clip_seconds,
        max_clip_seconds=config.max_clip_seconds,
        max_candidates=config.candidates_per_window,
        language=language,
    )


def _analyze_with_retry(
    provider: ClipAnalysisProvider,
    request: ClipAnalysisRequest,
    settings: Settings,
    sleep: Callable[[float], None],
) -> ClipAnalysisResult:
    """Bounded exponential backoff for transient provider errors only."""
    attempts = settings.clip_detection_provider_max_attempts
    for attempt in range(1, attempts + 1):
        try:
            return provider.analyze(request)
        except ClipProviderError as error:
            if not error.retryable or attempt == attempts:
                raise
            delay = settings.clip_detection_retry_backoff_seconds * (2 ** (attempt - 1))
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


def _ensure_still_owner(run: ClipDetectionRun, db: Session, task_id: str | None) -> None:
    """Re-read the fencing token; a newer task id means this run must stop writing."""
    if task_id is None:
        return
    current = db.scalar(
        select(ClipDetectionRun.celery_task_id).where(ClipDetectionRun.id == run.id)
    )
    if current and current != task_id:
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(run: ClipDetectionRun, db: Session, task_id: str | None = None) -> None:
    """Commit progress — but only while this task still owns the run."""
    _ensure_still_owner(run, db, task_id)
    run.heartbeat_at = _now()
    db.commit()


def _fail(
    run: ClipDetectionRun, db: Session, code: str, message: str, *, task_id: str | None = None
) -> None:
    db.rollback()  # discard anything uncommitted from the failed step
    current = (
        db.scalar(select(ClipDetectionRun.celery_task_id).where(ClipDetectionRun.id == run.id))
        if task_id
        else None
    )
    if current and current != task_id:
        logger.info(
            "Clip detection %s failed (%s) after being taken over; newer attempt untouched",
            run.id,
            code,
        )
        return
    run.status = ClipDetectionStatus.FAILED
    run.error_code = code[:64]
    run.error_message = message[:MAX_ERROR_LENGTH]
    run.completed_at = _now()
    run.heartbeat_at = run.completed_at
    db.execute(delete(ClipCandidate).where(ClipCandidate.run_id == run.id))
    db.commit()
    logger.warning("Clip detection %s failed: %s — %s", run.id, code, message)
