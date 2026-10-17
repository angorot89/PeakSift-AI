"""B-roll suggestions for a generated clip: state, start (idempotent per server configuration),
regenerate, status, retry, and the creator's decision on each suggestion.

Ownership chain: User → Project → Video → Clip → BrollAnalysis → BrollSuggestion; anything
else is a 404 (401 without a session). A request can only ask "suggest B-roll for this clip"
(or, deliberately, "regenerate"): the provider, model and every rule are server
configuration in a versioned snapshot. Responses never carry prompts, raw model output,
scores, provider internals, task ids or fingerprints. Suggestions describe *what* to show;
they are never tied to an asset or a source here.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.clip_edits import OwnedClip
from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import (
    ACTIVE_BROLL_ANALYSIS_STATUSES,
    BrollAnalysis,
    BrollAnalysisStatus,
    BrollSuggestion,
    Clip,
    ClipStatus,
    TranscriptionStatus,
)
from app.schemas.broll import (
    BrollAnalysisRead,
    BrollStartRequest,
    BrollStateRead,
    BrollSuggestionRead,
    BrollSuggestionUpdate,
)
from app.services.broll.config import BrollConfig
from app.services.broll.pipeline import is_stale
from app.workers.dispatch import JobQueueUnavailable, enqueue_broll_analysis, new_task_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clips/{clip_id}/broll", tags=["broll"]
)


def get_owned_analysis(analysis_id: uuid.UUID, clip: OwnedClip, db: DbSession) -> BrollAnalysis:
    analysis = db.scalar(
        select(BrollAnalysis).where(
            BrollAnalysis.id == analysis_id, BrollAnalysis.clip_id == clip.id
        )
    )
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis


def get_owned_suggestion(
    suggestion_id: uuid.UUID, clip: OwnedClip, db: DbSession
) -> BrollSuggestion:
    suggestion = db.scalar(
        select(BrollSuggestion).where(
            BrollSuggestion.id == suggestion_id, BrollSuggestion.clip_id == clip.id
        )
    )
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    return suggestion


OwnedAnalysis = Annotated[BrollAnalysis, Depends(get_owned_analysis)]
OwnedSuggestion = Annotated[BrollSuggestion, Depends(get_owned_suggestion)]


def method(analysis: BrollAnalysis) -> str:
    """How the suggestions were made, in plain terms (never a provider class)."""
    if analysis.provider == "keyword":
        return "keyword_fallback" if analysis.fallback_reason else "keyword"
    return "local_ai"


def _read(analysis: BrollAnalysis) -> BrollAnalysisRead:
    return BrollAnalysisRead(
        id=analysis.id,
        clip_id=analysis.clip_id,
        status=analysis.status,
        progress_percent=analysis.progress_percent,
        attempt=analysis.attempt,
        is_stale=is_stale(analysis, get_settings()),
        generation=analysis.generation,
        method=method(analysis),
        suggestion_count=analysis.suggestion_count,
        rejected_count=analysis.rejected_count,
        error_code=analysis.error_code,
        error_message=analysis.error_message,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


def _suggestion(row: BrollSuggestion) -> BrollSuggestionRead:
    return BrollSuggestionRead(
        id=row.id,
        analysis_id=row.analysis_id,
        start=row.start_time,
        end=row.end_time,
        query=row.query,
        reason=row.reason,
        status=row.status,
    )


def _base(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """The configuration without its generation: what "the same settings" means."""
    return {k: v for k, v in (snapshot or {}).items() if k != "generation"}


def _current(db: DbSession, clip: Clip) -> BrollAnalysis | None:
    """The newest analysis made with the server's current settings (any generation)."""
    wanted = _base(BrollConfig.from_settings(get_settings()).snapshot())
    rows = db.scalars(
        select(BrollAnalysis)
        .where(BrollAnalysis.clip_id == clip.id)
        .order_by(BrollAnalysis.generation.desc(), BrollAnalysis.created_at.desc())
    )
    return next((row for row in rows if _base(row.config) == wanted), None)


def _suggestions(db: DbSession, analysis: BrollAnalysis) -> list[BrollSuggestionRead]:
    if analysis.status != BrollAnalysisStatus.COMPLETED:
        return []
    rows = db.scalars(
        select(BrollSuggestion)
        .where(BrollSuggestion.analysis_id == analysis.id)
        .order_by(BrollSuggestion.sequence_index)
    )
    return [_suggestion(row) for row in rows]


def _require_suggestable(clip: Clip) -> None:
    if clip.status != ClipStatus.READY or not clip.duration_seconds:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generate the clip before asking for B-roll",
        )
    transcription = clip.video.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="B-roll suggestions need a completed transcript for this video",
        )


def _enqueue_or_503(db: DbSession, analysis: BrollAnalysis, *, created: bool) -> None:
    """The attempt token is already committed on the row; hand the job to the broker."""
    try:
        enqueue_broll_analysis(analysis.id, task_id=analysis.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(analysis)  # never leave a queued row that no worker will pick up
        else:
            analysis.status = BrollAnalysisStatus.FAILED
            analysis.error_code = "queue_unavailable"
            analysis.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The suggestion queue is unavailable. Try again in a moment.",
        ) from None


@router.get("", response_model=BrollStateRead)
def broll_state(clip: OwnedClip, db: DbSession) -> BrollStateRead:
    """The current analysis (if any) and, once completed, its suggestions in time order."""
    analysis = _current(db, clip)
    return BrollStateRead(
        analysis=_read(analysis) if analysis else None,
        suggestions=_suggestions(db, analysis) if analysis else [],
    )


@router.post(
    "/analyses",
    response_model=BrollAnalysisRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("broll_suggest")],
)
def start_analysis(
    clip: OwnedClip, db: DbSession, response: Response, body: BrollStartRequest | None = None
) -> BrollAnalysisRead:
    """Suggest B-roll with the server's settings. Asking again returns the current analysis
    (200); ``regenerate`` deliberately makes a new one once the current one has finished."""
    regenerate = bool(body and body.regenerate)
    current = _current(db, clip)
    if current is not None and not regenerate:
        if current.status == BrollAnalysisStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last suggestion run failed; use the retry endpoint",
            )
        response.status_code = status.HTTP_200_OK
        return _read(current)
    if current is not None and current.status in ACTIVE_BROLL_ANALYSIS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Suggestions are still being made; wait for them before regenerating",
        )
    _require_suggestable(clip)
    generation = current.generation + 1 if current is not None else 1
    config = BrollConfig.from_settings(get_settings(), generation=generation)
    analysis = BrollAnalysis(
        clip_id=clip.id,
        video_id=clip.video_id,
        config=config.snapshot(),
        config_fingerprint=config.fingerprint(),
        generation=generation,
        suggestion_version=config.suggestion_version,
        provider=config.provider,
        model=config.model,
        celery_task_id=new_task_id(),  # attempt token committed before the job exists
    )
    db.add(analysis)
    try:
        db.commit()
    except IntegrityError:  # a concurrent identical request won the unique constraint
        db.rollback()
        winner = _current(db, clip)
        if winner is None:  # pragma: no cover - the other transaction vanished
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Try again") from None
        response.status_code = status.HTTP_200_OK
        return _read(winner)
    _enqueue_or_503(db, analysis, created=True)
    return _read(analysis)


@router.get("/analyses/{analysis_id}", response_model=BrollAnalysisRead)
def get_analysis(analysis: OwnedAnalysis) -> BrollAnalysisRead:
    return _read(analysis)


@router.get("/analyses/{analysis_id}/suggestions", response_model=list[BrollSuggestionRead])
def list_suggestions(analysis: OwnedAnalysis, db: DbSession) -> list[BrollSuggestionRead]:
    """The analysis' suggestions in time order (409 until it has completed)."""
    if analysis.status != BrollAnalysisStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The suggestions are not ready yet"
        )
    return _suggestions(db, analysis)


@router.post(
    "/analyses/{analysis_id}/retry",
    response_model=BrollAnalysisRead,
    dependencies=[per_user("broll_suggest")],
)
def retry_analysis(analysis: OwnedAnalysis, clip: OwnedClip, db: DbSession) -> BrollAnalysisRead:
    """Re-queue a failed or stalled analysis on the same row with a fresh attempt token."""
    settings = get_settings()
    db.refresh(analysis, with_for_update=True)  # concurrent retries serialize
    if analysis.status != BrollAnalysisStatus.FAILED and not is_stale(analysis, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled suggestion run can be retried",
        )
    if analysis.attempt >= settings.broll_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This suggestion run has been retried too many times",
        )
    _require_suggestable(clip)
    db.execute(delete(BrollSuggestion).where(BrollSuggestion.analysis_id == analysis.id))
    analysis.status = BrollAnalysisStatus.QUEUED
    analysis.progress_percent = 0
    analysis.attempt += 1
    analysis.error_code = analysis.error_message = None
    analysis.started_at = analysis.completed_at = analysis.heartbeat_at = None
    analysis.celery_task_id = new_task_id()  # fences out a stalled worker of the old attempt
    db.commit()
    _enqueue_or_503(db, analysis, created=False)
    return _read(analysis)


@router.patch("/suggestions/{suggestion_id}", response_model=BrollSuggestionRead)
def update_suggestion(
    suggestion: OwnedSuggestion, body: BrollSuggestionUpdate, db: DbSession
) -> BrollSuggestionRead:
    """The creator's decision: accepted (used), dismissed, or back to suggested. It never
    changes what is rendered by itself — visuals are placed in an edit's configuration."""
    suggestion.status = body.status.value
    db.commit()
    return _suggestion(suggestion)
