"""AI clip detection: providers, start/status/retry/list runs, ranked candidates, decisions.

Every route is scoped User → Project → Video → Run → Candidate; anything outside that
chain is an indistinguishable 404. Provider and model come from the client but are
validated against server allow-lists; endpoints and keys never leave the server.
"""

import uuid
from datetime import UTC, datetime
from types import EllipsisType
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.api.transcriptions import OwnedVideo
from app.core.config import get_settings
from app.models import (
    ACTIVE_CLIP_DETECTION_STATUSES,
    CandidateDecision,
    ClipCandidate,
    ClipDetectionRun,
    ClipDetectionStatus,
    TranscriptionStatus,
    TranscriptSegment,
    Video,
    VideoStatus,
)
from app.schemas.clip_detection import (
    CandidatePage,
    CandidateScores,
    ClipCandidateRead,
    DetectionRunPage,
    DetectionRunRead,
    ProviderOptionRead,
    StartDetectionRequest,
)
from app.services.clip_detection.contract import ClipProviderConfigurationError, TranscriptLine
from app.services.clip_detection.detection_config import DetectionConfig
from app.services.clip_detection.factory import (
    get_clip_provider,
    provider_options,
    resolve_choice,
)
from app.services.clip_detection.pipeline import is_stale
from app.services.clip_detection.windowing import (
    TranscriptError,
    prepare_lines,
    transcript_fingerprint,
)
from app.workers.dispatch import JobQueueUnavailable, enqueue_clip_detection, new_task_id

providers_router = APIRouter(prefix="/clip-detection", tags=["clip-detection"])
router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clip-detection", tags=["clip-detection"]
)

MAX_PAGE_SIZE = 100


# --- providers -------------------------------------------------------------------------


@providers_router.get("/providers", response_model=list[ProviderOptionRead])
def list_providers(_: CurrentUser, diagnose: bool = False) -> list[ProviderOptionRead]:
    """What the user may choose. With ?diagnose=true each configured provider is probed."""
    settings = get_settings()
    result: list[ProviderOptionRead] = []
    for option in provider_options(settings):
        read = ProviderOptionRead(
            name=option.name,
            label=option.label,
            models=list(option.models),
            default_model=option.default_model,
            configured=option.configured,
            detail=option.reason,
        )
        if diagnose and option.configured and option.default_model:
            try:
                diagnostics = get_clip_provider(
                    option.name, option.default_model, settings
                ).check_availability()
                read.available, read.detail = diagnostics.available, diagnostics.detail
            except ClipProviderConfigurationError as error:
                read.available, read.detail = False, error.message
        result.append(read)
    return result


# --- helpers ----------------------------------------------------------------------------


def _candidate_count(db: DbSession, run: ClipDetectionRun) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(ClipCandidate).where(ClipCandidate.run_id == run.id)
        )
        or 0
    )


def _current_lines(db: DbSession, video: Video, settings) -> tuple[TranscriptLine, ...]:
    """The video's completed transcript as analysable lines, or an HTTP 409."""
    transcription = video.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transcribe the video before detecting clips",
        )
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_id == transcription.id)
        .order_by(TranscriptSegment.sequence_index)
    )
    try:
        return prepare_lines(
            (TranscriptLine(s.start_time, s.end_time, s.text) for s in segments),
            video_duration=float(video.duration_seconds or 0.0),
            tolerance_seconds=settings.clip_detection_timestamp_tolerance_seconds,
        )
    except TranscriptError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message) from None


def _current_fingerprint(db: DbSession, video: Video) -> str | None:
    transcription = video.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        return None
    try:
        lines = _current_lines(db, video, get_settings())
    except HTTPException:
        return None
    return transcript_fingerprint(transcription.id, lines)


def _read(
    db: DbSession, run: ClipDetectionRun, *, current_fingerprint: str | None | EllipsisType
) -> DetectionRunRead:
    """``current_fingerprint`` is ``...`` when the caller did not evaluate it (active runs are
    polled every few seconds; hashing a multi-hour transcript each time would be waste)."""
    if current_fingerprint is Ellipsis:
        transcript_current = None
    else:
        transcript_current = current_fingerprint == run.transcript_fingerprint
    return DetectionRunRead(
        id=run.id,
        video_id=run.video_id,
        transcription_id=run.transcription_id,
        provider=run.provider,
        model=run.model,
        status=run.status,
        progress_percent=run.progress_percent,
        windows_total=run.windows_total,
        windows_done=run.windows_done,
        attempt=run.attempt,
        candidate_count=_candidate_count(db, run),
        is_stale=is_stale(run, get_settings()),
        transcript_current=transcript_current,
        config=run.config or {},
        error_code=run.error_code,
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _read_candidate(candidate: ClipCandidate) -> ClipCandidateRead:
    return ClipCandidateRead(
        id=candidate.id,
        run_id=candidate.run_id,
        video_id=candidate.video_id,
        rank=candidate.rank,
        start=candidate.start_time,
        end=candidate.end_time,
        duration=candidate.duration_seconds,
        title=candidate.title,
        hook=candidate.hook,
        rationale=candidate.rationale,
        category=candidate.category,
        transcript_excerpt=candidate.transcript_excerpt,
        overall_score=candidate.overall_score,
        scores=CandidateScores(
            hook=candidate.hook_score,
            entertainment=candidate.entertainment_score,
            clarity=candidate.clarity_score,
            payoff=candidate.payoff_score,
            completeness=candidate.completeness_score,
        ),
        decision=candidate.decision,
        decided_at=candidate.decided_at,
        created_at=candidate.created_at,
    )


def _active_run(db: DbSession, video: Video) -> ClipDetectionRun | None:
    return db.scalar(
        select(ClipDetectionRun).where(
            ClipDetectionRun.video_id == video.id,
            ClipDetectionRun.status.in_([s.value for s in ACTIVE_CLIP_DETECTION_STATUSES]),
        )
    )


def get_owned_run(run_id: uuid.UUID, video: OwnedVideo, db: DbSession) -> ClipDetectionRun:
    run = db.scalar(
        select(ClipDetectionRun).where(
            ClipDetectionRun.id == run_id, ClipDetectionRun.video_id == video.id
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection run not found")
    return run


OwnedRun = Annotated[ClipDetectionRun, Depends(get_owned_run)]


def get_owned_candidate(candidate_id: uuid.UUID, run: OwnedRun, db: DbSession) -> ClipCandidate:
    candidate = db.scalar(
        select(ClipCandidate).where(
            ClipCandidate.id == candidate_id, ClipCandidate.run_id == run.id
        )
    )
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return candidate


OwnedCandidate = Annotated[ClipCandidate, Depends(get_owned_candidate)]


def _enqueue_or_503(db: DbSession, run: ClipDetectionRun, *, created: bool) -> None:
    """The task id is already on the committed row; now hand the job to the broker."""
    try:
        enqueue_clip_detection(run.id, task_id=run.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(run)  # never leave a queued row that no worker will pick up
        else:
            run.status = ClipDetectionStatus.FAILED
            run.error_code = "queue_unavailable"
            run.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The clip detection queue is unavailable. Try again in a moment.",
        ) from None


# --- runs ---------------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DetectionRunRead)
def start_detection(
    body: StartDetectionRequest, video: OwnedVideo, db: DbSession
) -> DetectionRunRead:
    """Queue a detection run for a ready, transcribed video. One active run per video."""
    settings = get_settings()
    if video.status != VideoStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The video must be ready first"
        )
    lines = _current_lines(db, video, settings)
    try:
        provider, model = resolve_choice(body.provider, body.model, settings)
    except ClipProviderConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error.message) from None
    if _active_run(db, video) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A clip detection is already running for this video",
        )

    run = ClipDetectionRun(
        video=video,
        transcription=video.transcription,
        transcript_fingerprint=transcript_fingerprint(video.transcription.id, lines),
        provider=provider,
        model=model,
        config=DetectionConfig.from_settings(settings).as_dict(),
        celery_task_id=new_task_id(),  # fencing token committed before the job exists
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:  # a concurrent start won the one-active-run-per-video index
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A clip detection is already running for this video",
        ) from None
    _enqueue_or_503(db, run, created=True)
    return _read(db, run, current_fingerprint=run.transcript_fingerprint)


@router.get("", response_model=DetectionRunPage)
def list_runs(
    video: OwnedVideo,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> DetectionRunPage:
    """The video's detection runs, newest first."""
    total = (
        db.scalar(
            select(func.count())
            .select_from(ClipDetectionRun)
            .where(ClipDetectionRun.video_id == video.id)
        )
        or 0
    )
    runs = db.scalars(
        select(ClipDetectionRun)
        .where(ClipDetectionRun.video_id == video.id)
        .order_by(ClipDetectionRun.created_at.desc(), ClipDetectionRun.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    current = _current_fingerprint(db, video)
    return DetectionRunPage(
        total=total,
        offset=offset,
        limit=limit,
        runs=[_read(db, run, current_fingerprint=current) for run in runs],
    )


@router.get("/{run_id}", response_model=DetectionRunRead)
def get_run(run: OwnedRun, video: OwnedVideo, db: DbSession) -> DetectionRunRead:
    # While a run is active this endpoint is polled; the transcript check only matters once
    # there are results to compare against, so skip the full-transcript hash until then.
    active = run.status in {s.value for s in ACTIVE_CLIP_DETECTION_STATUSES}
    return _read(db, run, current_fingerprint=... if active else _current_fingerprint(db, video))


@router.post("/{run_id}/retry", response_model=DetectionRunRead)
def retry_run(run: OwnedRun, video: OwnedVideo, db: DbSession) -> DetectionRunRead:
    """Re-queue a failed or stalled run against the same transcript snapshot."""
    settings = get_settings()
    if run.status != ClipDetectionStatus.FAILED and not is_stale(run, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled detection can be retried",
        )
    if video.status != VideoStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The video must be ready first"
        )
    if run.attempt >= settings.clip_detection_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This detection has been retried too many times; start a new detection",
        )
    current = _current_fingerprint(db, video)
    if current != run.transcript_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The transcript has changed since this run; start a new detection instead",
        )
    other = _active_run(db, video)
    if other is not None and other.id != run.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A clip detection is already running for this video",
        )

    run.status = ClipDetectionStatus.QUEUED
    run.progress_percent = 0
    run.windows_total = None
    run.windows_done = 0
    run.attempt += 1
    run.error_code = None
    run.error_message = None
    run.started_at = None
    run.completed_at = None
    run.heartbeat_at = None
    run.celery_task_id = new_task_id()  # the old task, if still alive, is fenced out
    db.commit()
    _enqueue_or_503(db, run, created=False)
    return _read(db, run, current_fingerprint=current)


# --- candidates ------------------------------------------------------------------------------


def _require_completed(run: ClipDetectionRun) -> None:
    if run.status != ClipDetectionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Candidates are not available while the detection is {run.status}",
        )


@router.get("/{run_id}/candidates", response_model=CandidatePage)
def list_candidates(
    run: OwnedRun,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    decision: CandidateDecision | None = None,
) -> CandidatePage:
    """Ranked candidates of a completed run, optionally filtered by the user's decision."""
    _require_completed(run)
    where = [ClipCandidate.run_id == run.id]
    if decision is not None:
        where.append(ClipCandidate.decision == decision.value)
    total = db.scalar(select(func.count()).select_from(ClipCandidate).where(*where)) or 0
    candidates = db.scalars(
        select(ClipCandidate).where(*where).order_by(ClipCandidate.rank).offset(offset).limit(limit)
    ).all()
    return CandidatePage(
        run_id=run.id,
        total=total,
        offset=offset,
        limit=limit,
        candidates=[_read_candidate(c) for c in candidates],
    )


@router.get("/{run_id}/candidates/{candidate_id}", response_model=ClipCandidateRead)
def get_candidate(candidate: OwnedCandidate) -> ClipCandidateRead:
    return _read_candidate(candidate)


def _decide(
    db: DbSession, candidate: ClipCandidate, decision: CandidateDecision
) -> ClipCandidateRead:
    candidate.decision = decision.value
    candidate.decided_at = None if decision == CandidateDecision.UNDECIDED else datetime.now(UTC)
    db.commit()
    return _read_candidate(candidate)


@router.post("/{run_id}/candidates/{candidate_id}/save", response_model=ClipCandidateRead)
def save_candidate(candidate: OwnedCandidate, db: DbSession) -> ClipCandidateRead:
    return _decide(db, candidate, CandidateDecision.SAVED)


@router.post("/{run_id}/candidates/{candidate_id}/dismiss", response_model=ClipCandidateRead)
def dismiss_candidate(candidate: OwnedCandidate, db: DbSession) -> ClipCandidateRead:
    return _decide(db, candidate, CandidateDecision.DISMISSED)


@router.post("/{run_id}/candidates/{candidate_id}/reset", response_model=ClipCandidateRead)
def reset_candidate(candidate: OwnedCandidate, db: DbSession) -> ClipCandidateRead:
    """Back to undecided (undo a save or dismiss)."""
    return _decide(db, candidate, CandidateDecision.UNDECIDED)
