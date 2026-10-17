"""The B-roll suggestion job: clip transcript → provider → review → stored suggestions.

Runs in a Celery worker (``peaksift.suggest_broll``; only the analysis id crosses the
broker). The ``broll_analyses`` row is the source of truth:

- **Claiming:** a completed analysis is never re-run; a live one (fresh heartbeat) is not run
  twice; a failed one runs again only after the retry endpoint resets it; a row whose task id
  belongs to a newer attempt is ignored.
- **Ownership:** the task id committed before enqueueing is the attempt token. Every commit
  and the failure path re-read it, so a stalled worker that a retry took over never writes
  the row or its suggestions. A row deleted mid-run (its clip was removed) stops the job.
- **Input:** what was said in the clip, in clip-local seconds — word timing from the clip's
  latest completed caption track when there is one (precise), otherwise the persisted
  transcript segments overlapping the clip, shifted and bounded to it. No media is read.
- **Transactional result:** suggestions, counts and ``completed`` are written in ONE commit;
  a failure leaves no suggestions.
- **Honest progress:** stage-based (a language model exposes no reliable progress): 5
  claimed, 20 analyzing, 80 validating, 100 completed.

A suggestion job failing never affects editing or rendering: the editor works without it.
"""

import logging
import math
import uuid
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    BrollAnalysis,
    BrollAnalysisStatus,
    BrollSuggestion,
    BrollSuggestionStatus,
    CaptionTrack,
    CaptionTrackStatus,
    CaptionWord,
    Clip,
    ClipStatus,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.services.broll.config import BrollConfig
from app.services.broll.contract import (
    BrollProvider,
    BrollProviderError,
    BrollRequest,
    TranscriptLine,
)
from app.services.broll.suggest import get_broll_provider, review, suggest

logger = logging.getLogger(__name__)

CLAIMED_PROGRESS = 5
ANALYZING_PROGRESS = 20
VALIDATING_PROGRESS = 80
MAX_ERROR_LENGTH = 500
# Word timing is grouped into lines at pauses, sentence ends, or this many words.
LINE_MAX_WORDS = 12
LINE_PAUSE_SECONDS = 0.6


class PipelineSuperseded(Exception):
    """A newer attempt owns this analysis (or the row is gone); stop without writing."""


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(analysis: BrollAnalysis, settings: Settings, *, now: datetime | None = None) -> bool:
    if analysis.status not in (BrollAnalysisStatus.ANALYZING, BrollAnalysisStatus.VALIDATING):
        return False
    last = analysis.heartbeat_at or analysis.started_at or analysis.created_at
    return ((now or _now()) - last).total_seconds() > settings.broll_stale_after_seconds


def provider_for(config: BrollConfig, settings: Settings) -> BrollProvider:
    """The provider exactly as the analysis' snapshot describes it (not today's defaults)."""
    return get_broll_provider(settings, config.provider, config.model)


def run_broll_analysis(
    analysis_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    provider: BrollProvider | None = None,
    task_id: str | None = None,
) -> BrollAnalysis | None:
    """Suggest B-roll for one ``BrollAnalysis`` row. Problems are recorded, never raised."""
    settings = settings or get_settings()
    analysis = db.get(BrollAnalysis, analysis_id)
    if analysis is None:
        logger.warning("B-roll analysis %s no longer exists; nothing to do", analysis_id)
        return None
    if not _claim(analysis, db, settings, task_id):
        return analysis

    def fail(code: str, message: str) -> None:
        try:
            _fail(analysis, db, code, message, task_id=task_id)
        except Exception:
            # The database itself is failing: leave the row to go stale; retry recovers it.
            logger.exception("Could not record the failure of B-roll analysis %s", analysis_id)
            db.rollback()

    try:
        _execute(analysis, db, settings, provider, task_id)
    except PipelineSuperseded:
        logger.info("B-roll analysis %s was taken over or removed; stopping", analysis_id)
    except PipelineFailure as error:
        fail(error.code, error.message)
    except BrollProviderError as error:
        fail(error.code, error.message)
    except SoftTimeLimitExceeded:
        fail("time_limit", "Suggesting B-roll ran longer than the worker allows; retry it")
    except Exception:
        logger.exception("Unexpected error suggesting B-roll for analysis %s", analysis_id)
        fail("internal_error", "Unexpected error while suggesting B-roll")
    return analysis


# --- claiming -----------------------------------------------------------------------------------


def _claim(analysis: BrollAnalysis, db: Session, settings: Settings, task_id: str | None) -> bool:
    if task_id and analysis.celery_task_id and analysis.celery_task_id != task_id:
        logger.info("B-roll analysis %s belongs to a newer attempt; ignoring", analysis.id)
        return False
    if analysis.status == BrollAnalysisStatus.COMPLETED:
        logger.info("B-roll analysis %s is already completed; ignoring duplicate task", analysis.id)
        return False
    if analysis.status == BrollAnalysisStatus.FAILED:
        logger.info("B-roll analysis %s is failed; a retry must reset it first", analysis.id)
        return False
    if analysis.status != BrollAnalysisStatus.QUEUED and not is_stale(analysis, settings):
        logger.info("B-roll analysis %s is already running elsewhere", analysis.id)
        return False
    now = _now()
    db.execute(delete(BrollSuggestion).where(BrollSuggestion.analysis_id == analysis.id))
    analysis.status = BrollAnalysisStatus.ANALYZING
    analysis.progress_percent = CLAIMED_PROGRESS
    analysis.started_at = analysis.heartbeat_at = now
    analysis.completed_at = None
    analysis.error_code = analysis.error_message = None
    analysis.fallback_reason = None
    analysis.suggestion_count = analysis.rejected_count = None
    db.commit()
    return True


# --- input: what was said, in clip-local seconds -------------------------------------------------


def lines_from_words(words: list[CaptionWord], duration: float) -> tuple[TranscriptLine, ...]:
    """Group timed words into short lines at pauses, sentence ends or LINE_MAX_WORDS."""
    lines: list[TranscriptLine] = []
    current: list[CaptionWord] = []

    def flush() -> None:
        if current:
            start, end = current[0].start_time, min(current[-1].end_time, duration)
            if end > start:
                lines.append(TranscriptLine(start, end, " ".join(w.text.strip() for w in current)))
            current.clear()

    for word in words:
        if word.start_time >= duration:
            break
        if current and (
            word.start_time - current[-1].end_time >= LINE_PAUSE_SECONDS
            or len(current) >= LINE_MAX_WORDS
            or current[-1].text.rstrip().endswith((".", "!", "?"))
        ):
            flush()
        current.append(word)
    flush()
    return tuple(lines)


def clip_lines(clip: Clip, db: Session) -> tuple[TranscriptLine, ...]:
    duration = float(clip.duration_seconds)
    track = db.scalar(
        select(CaptionTrack)
        .where(CaptionTrack.clip_id == clip.id, CaptionTrack.status == CaptionTrackStatus.COMPLETED)
        .order_by(CaptionTrack.completed_at.desc().nulls_last(), CaptionTrack.created_at.desc())
        .limit(1)
    )
    if track is not None:
        words = list(
            db.scalars(
                select(CaptionWord)
                .where(CaptionWord.caption_track_id == track.id)
                .order_by(CaptionWord.sequence_index)
            )
        )
        if words:
            return lines_from_words(words, duration)
    transcription = clip.video.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        raise PipelineFailure(
            "transcript_unavailable", "B-roll suggestions need a completed transcript"
        )
    segments = db.scalars(
        select(TranscriptSegment)
        .where(
            TranscriptSegment.transcription_id == transcription.id,
            TranscriptSegment.end_time > clip.start_time,
            TranscriptSegment.start_time < clip.end_time,
        )
        .order_by(TranscriptSegment.sequence_index)
    )
    lines = []
    for segment in segments:
        start = max(0.0, float(segment.start_time) - clip.start_time)
        end = min(duration, float(segment.end_time) - clip.start_time)
        text = " ".join(segment.text.split())
        if end > start and text:
            lines.append(TranscriptLine(round(start, 3), round(end, 3), text))
    return tuple(lines)


# --- the work -----------------------------------------------------------------------------------


def _execute(
    analysis: BrollAnalysis,
    db: Session,
    settings: Settings,
    provider: BrollProvider | None,
    task_id: str | None,
) -> None:
    try:
        config = BrollConfig.from_snapshot(analysis.config)  # the stored snapshot
    except ValueError:
        raise PipelineFailure(
            "config_invalid", "The B-roll suggestion configuration is not supported"
        ) from None
    clip = analysis.clip
    if clip.status != ClipStatus.READY or not clip.duration_seconds:
        raise PipelineFailure("clip_not_ready", "The clip is not ready")
    duration = float(clip.duration_seconds)
    lines = clip_lines(clip, db)
    analysis.clip_duration_seconds = round(duration, 3)
    analysis.progress_percent = ANALYZING_PROGRESS
    _heartbeat(analysis, db, task_id)

    if not lines:  # nothing was said: nothing to illustrate, honestly
        _ensure_still_owner(analysis, db, task_id)
        _finalize(analysis, db, [], rejected=0, provider=config.provider, model=config.model,
                  fallback_reason=None)  # fmt: skip
        _heartbeat(analysis, db, task_id)
        return

    request = BrollRequest(
        lines=lines,
        clip_duration=duration,
        max_suggestions=max(
            1, min(config.max_suggestions, math.floor(duration / config.seconds_per_suggestion))
        ),
        min_seconds=config.min_seconds,
        max_seconds=config.max_seconds,
        title=clip.candidate.title if clip.candidate else None,
        hook=clip.candidate.hook if clip.candidate else None,
    )
    outcome = suggest(
        request,
        provider or provider_for(config, settings),
        fallback_enabled=config.fallback_enabled,
    )

    analysis.status = BrollAnalysisStatus.VALIDATING
    analysis.progress_percent = VALIDATING_PROGRESS
    _heartbeat(analysis, db, task_id)
    report = review(outcome.result.suggestions, lines, duration)

    _ensure_still_owner(analysis, db, task_id)
    _finalize(
        analysis,
        db,
        report.kept,
        rejected=report.rejected_count,
        provider=outcome.result.provider,
        model=outcome.result.model,
        fallback_reason=outcome.fallback_reason,
    )
    _heartbeat(analysis, db, task_id)
    logger.info(
        "B-roll analysis %s completed: %d suggestions (%d rejected: %s) by %s%s",
        analysis.id,
        len(report.kept),
        report.rejected_count,
        report.rejected,
        outcome.result.provider,
        f" (fallback: {outcome.fallback_reason})" if outcome.fallback_reason else "",
    )


def _finalize(
    analysis: BrollAnalysis,
    db: Session,
    kept: list,
    *,
    rejected: int,
    provider: str,
    model: str,
    fallback_reason: str | None,
) -> None:
    db.execute(delete(BrollSuggestion).where(BrollSuggestion.analysis_id == analysis.id))
    db.add_all(
        BrollSuggestion(
            analysis_id=analysis.id,
            clip_id=analysis.clip_id,
            sequence_index=index,
            start_time=item.start,
            end_time=item.end,
            query=item.query,
            reason=item.reason,
            score=item.score,
            status=BrollSuggestionStatus.SUGGESTED,
            provider=provider[:64],
            provider_version=model[:128],
        )
        for index, item in enumerate(kept)
    )
    analysis.provider = provider[:64]
    analysis.model = model[:128]
    analysis.fallback_reason = fallback_reason[:64] if fallback_reason else None
    analysis.suggestion_count = len(kept)
    analysis.rejected_count = rejected
    analysis.status = BrollAnalysisStatus.COMPLETED
    analysis.progress_percent = 100
    analysis.completed_at = _now()


# --- state helpers ------------------------------------------------------------------------------


def _key(analysis: BrollAnalysis) -> uuid.UUID:
    """The primary key without a database round trip (safe if the row was deleted)."""
    return sa_inspect(analysis).identity[0]


def _still_owner(analysis: BrollAnalysis, db: Session, task_id: str | None) -> bool:
    with db.no_autoflush:  # read the committed token; never flush pending progress first
        row = db.execute(
            select(BrollAnalysis.celery_task_id).where(BrollAnalysis.id == _key(analysis))
        ).first()
    if row is None:
        return False
    if task_id is None:
        return True
    return not row.celery_task_id or row.celery_task_id == task_id


def _ensure_still_owner(analysis: BrollAnalysis, db: Session, task_id: str | None) -> None:
    if not _still_owner(analysis, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(analysis: BrollAnalysis, db: Session, task_id: str | None = None) -> None:
    """Commit progress — but only while this attempt still owns the analysis."""
    _ensure_still_owner(analysis, db, task_id)
    analysis.heartbeat_at = _now()
    db.commit()


def _fail(
    analysis: BrollAnalysis, db: Session, code: str, message: str, *, task_id: str | None = None
) -> None:
    db.rollback()
    analysis_id = _key(analysis)
    if not _still_owner(analysis, db, task_id):
        logger.info(
            "B-roll analysis %s failed (%s) after being taken over; ignoring", analysis_id, code
        )
        return
    db.execute(delete(BrollSuggestion).where(BrollSuggestion.analysis_id == analysis_id))
    analysis.status = BrollAnalysisStatus.FAILED
    analysis.error_code = code[:64]
    analysis.error_message = message[:MAX_ERROR_LENGTH]
    analysis.completed_at = _now()
    analysis.heartbeat_at = analysis.completed_at
    db.commit()
    logger.warning("B-roll analysis %s failed: %s — %s", analysis_id, code, message)
