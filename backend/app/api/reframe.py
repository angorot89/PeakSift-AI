"""Smart reframing of generated clips: start (idempotent per server configuration), list,
current, status, crop path and retry.

Ownership chain: User → Project → Video → Clip → ReframeAnalysis; anything else is a 404 (401
without a session). A request can only ask "analyse this clip": the detector, model file and
every tuning value are server configuration, captured in a snapshot whose fingerprint makes
``(clip_id, config_fingerprint)`` unique — repeated clicks return the same analysis.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.clip_edits import OwnedClip
from app.api.deps import DbSession, Storage
from app.api.media_streaming import object_present
from app.core.config import get_settings
from app.models import (
    Clip,
    ClipStatus,
    ReframeAnalysis,
    ReframeKeyframe,
    ReframeStatus,
)
from app.schemas.reframe import (
    CropKeyframeRead,
    CropPathRead,
    ReframeAnalysisPage,
    ReframeAnalysisRead,
)
from app.services.reframe.config import ReframeConfig
from app.services.reframe.detection import detector_available
from app.services.reframe.pipeline import is_stale
from app.services.storage import StorageProvider
from app.workers.dispatch import JobQueueUnavailable, enqueue_reframe_analysis, new_task_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clips/{clip_id}/reframe", tags=["reframe"]
)

MAX_LIST = 20


def get_owned_analysis(analysis_id: uuid.UUID, clip: OwnedClip, db: DbSession) -> ReframeAnalysis:
    analysis = db.scalar(
        select(ReframeAnalysis).where(
            ReframeAnalysis.id == analysis_id, ReframeAnalysis.clip_id == clip.id
        )
    )
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis


OwnedAnalysis = Annotated[ReframeAnalysis, Depends(get_owned_analysis)]


def _read(analysis: ReframeAnalysis) -> ReframeAnalysisRead:
    return ReframeAnalysisRead(
        id=analysis.id,
        clip_id=analysis.clip_id,
        status=analysis.status,
        progress_percent=analysis.progress_percent,
        attempt=analysis.attempt,
        is_stale=is_stale(analysis, get_settings()),
        provider=analysis.provider,
        algorithm_version=analysis.algorithm_version,
        sample_fps=analysis.sample_fps,
        target_aspect_ratio=analysis.target_aspect_ratio,
        source_width=analysis.source_width,
        source_height=analysis.source_height,
        overall_confidence=analysis.overall_confidence,
        confidence_level=analysis.confidence_level,
        frames_sampled=analysis.frames_sampled,
        detections_count=analysis.detections_count,
        tracks_count=analysis.tracks_count,
        subject_switches=analysis.subject_switches,
        fallback_fraction=analysis.fallback_fraction,
        error_code=analysis.error_code,
        error_message=analysis.error_message,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


def _require_analysable(clip: Clip, storage: StorageProvider) -> None:
    if clip.status != ClipStatus.READY or not clip.storage_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Generate the clip before framing it"
        )
    present = object_present(storage, clip.storage_key)
    if not present:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The clip file is missing; generate the clip again",
        )
    if not detector_available(get_settings()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Smart framing is not available on this server",
        )


def _current(db: DbSession, clip: Clip, fingerprint: str) -> ReframeAnalysis | None:
    return db.scalar(
        select(ReframeAnalysis).where(
            ReframeAnalysis.clip_id == clip.id, ReframeAnalysis.config_fingerprint == fingerprint
        )
    )


def _enqueue_or_503(db: DbSession, analysis: ReframeAnalysis, *, created: bool) -> None:
    """The attempt token is already committed on the row; hand the job to the broker."""
    try:
        enqueue_reframe_analysis(analysis.id, task_id=analysis.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(analysis)  # never leave a queued row that no worker will pick up
        else:
            analysis.status = ReframeStatus.FAILED
            analysis.error_code = "queue_unavailable"
            analysis.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis queue is unavailable. Try again in a moment.",
        ) from None


@router.post("", response_model=ReframeAnalysisRead, status_code=status.HTTP_201_CREATED)
def start_analysis(clip: OwnedClip, db: DbSession, storage: Storage, response: Response):
    """Analyse the clip's framing with the server's current configuration. The same
    configuration returns the existing analysis (200); a failed one must be retried (409)."""
    settings = get_settings()
    config = ReframeConfig.from_settings(settings)
    fingerprint = config.fingerprint()
    existing = _current(db, clip, fingerprint)
    if existing is not None:
        if existing.status == ReframeStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last framing analysis failed; use the retry endpoint",
            )
        response.status_code = status.HTTP_200_OK
        return _read(existing)

    _require_analysable(clip, storage)
    analysis = ReframeAnalysis(
        clip_id=clip.id,
        video_id=clip.video_id,
        provider=config.detector,
        algorithm_version=config.algorithm_version,
        config=config.snapshot(),
        config_fingerprint=fingerprint,
        sample_fps=config.sample_fps,
        target_aspect_ratio=config.target_aspect_ratio,
        celery_task_id=new_task_id(),  # attempt token committed before the job exists
    )
    db.add(analysis)
    try:
        db.commit()
    except IntegrityError:  # a concurrent identical request won the unique constraint
        db.rollback()
        winner = _current(db, clip, fingerprint)
        if winner is None:  # pragma: no cover - the other transaction vanished
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Try again") from None
        response.status_code = status.HTTP_200_OK
        return _read(winner)
    _enqueue_or_503(db, analysis, created=True)
    return _read(analysis)


@router.get("", response_model=ReframeAnalysisPage)
def list_analyses(clip: OwnedClip, db: DbSession) -> ReframeAnalysisPage:
    """The clip's analyses, newest first (several exist only if the server config changed)."""
    total = (
        db.scalar(
            select(func.count())
            .select_from(ReframeAnalysis)
            .where(ReframeAnalysis.clip_id == clip.id)
        )
        or 0
    )
    rows = db.scalars(
        select(ReframeAnalysis)
        .where(ReframeAnalysis.clip_id == clip.id)
        .order_by(ReframeAnalysis.created_at.desc(), ReframeAnalysis.id.desc())
        .limit(MAX_LIST)
    ).all()
    return ReframeAnalysisPage(total=total, analyses=[_read(r) for r in rows])


@router.get("/current", response_model=ReframeAnalysisRead)
def current_analysis(clip: OwnedClip, db: DbSession) -> ReframeAnalysisRead:
    """The analysis for the server's current configuration (404 if none yet)."""
    analysis = _current(db, clip, ReframeConfig.from_settings(get_settings()).fingerprint())
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No framing analysis yet")
    return _read(analysis)


@router.get("/{analysis_id}", response_model=ReframeAnalysisRead)
def get_analysis(analysis: OwnedAnalysis) -> ReframeAnalysisRead:
    return _read(analysis)


@router.get("/{analysis_id}/path", response_model=CropPathRead)
def get_crop_path(analysis: OwnedAnalysis, db: DbSession) -> CropPathRead:
    """The completed crop path in order (409 until the analysis has completed)."""
    if analysis.status != ReframeStatus.COMPLETED or not analysis.source_width:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The framing analysis is not complete"
        )
    points = db.scalars(
        select(ReframeKeyframe)
        .where(ReframeKeyframe.reframe_analysis_id == analysis.id)
        .order_by(ReframeKeyframe.sequence_index)
    ).all()
    return CropPathRead(
        analysis_id=analysis.id,
        source_width=analysis.source_width,
        source_height=analysis.source_height,
        target_aspect_ratio=analysis.target_aspect_ratio,
        keyframes=[
            CropKeyframeRead(
                timestamp=p.timestamp,
                center_x=p.center_x,
                center_y=p.center_y,
                crop_width=p.crop_width,
                crop_height=p.crop_height,
                confidence=p.confidence,
                mode=p.mode,
            )
            for p in points
        ],
    )


@router.post("/{analysis_id}/retry", response_model=ReframeAnalysisRead)
def retry_analysis(
    analysis: OwnedAnalysis, clip: OwnedClip, db: DbSession, storage: Storage
) -> ReframeAnalysisRead:
    """Re-queue a failed or stalled analysis on the same row with a fresh attempt token."""
    settings = get_settings()
    # Lock the row until the commit below: concurrent retries serialize and the second sees
    # "queued" (409) instead of enqueueing a duplicate job.
    db.refresh(analysis, with_for_update=True)
    if analysis.status != ReframeStatus.FAILED and not is_stale(analysis, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled analysis can be retried",
        )
    if analysis.attempt >= settings.reframe_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This analysis has been retried too many times",
        )
    _require_analysable(clip, storage)
    db.execute(delete(ReframeKeyframe).where(ReframeKeyframe.reframe_analysis_id == analysis.id))
    analysis.status = ReframeStatus.QUEUED
    analysis.progress_percent = 0
    analysis.attempt += 1
    analysis.error_code = analysis.error_message = None
    analysis.started_at = analysis.completed_at = analysis.heartbeat_at = None
    analysis.celery_task_id = new_task_id()  # fences out a stalled worker of the old attempt
    db.commit()
    _enqueue_or_503(db, analysis, created=False)
    return _read(analysis)
