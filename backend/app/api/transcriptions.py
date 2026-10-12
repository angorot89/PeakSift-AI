import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.videos import OwnedProject
from app.core.config import get_settings
from app.models import (
    Transcription,
    TranscriptionStatus,
    TranscriptSegment,
    Video,
    VideoStatus,
)
from app.schemas.transcription import TranscriptionRead, TranscriptPage, TranscriptSegmentRead
from app.services.transcription.pipeline import is_stale
from app.workers.dispatch import JobQueueUnavailable, enqueue_transcription

router = APIRouter(prefix="/projects/{project_id}/videos/{video_id}", tags=["transcription"])

MAX_PAGE_SIZE = 500


def get_owned_video(video_id: uuid.UUID, project: OwnedProject, db: DbSession) -> Video:
    video = db.scalar(select(Video).where(Video.id == video_id, Video.project_id == project.id))
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return video


OwnedVideo = Annotated[Video, Depends(get_owned_video)]


def _configured_model(provider: str) -> str:
    settings = get_settings()
    if provider == "openai":
        return settings.openai_timestamp_model
    return settings.faster_whisper_model


def _segment_count(db: DbSession, transcription: Transcription) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.transcription_id == transcription.id)
        )
        or 0
    )


def _read(db: DbSession, transcription: Transcription) -> TranscriptionRead:
    return TranscriptionRead(
        id=transcription.id,
        video_id=transcription.video_id,
        status=transcription.status,
        provider=transcription.provider,
        model=transcription.model,
        language=transcription.language,
        language_probability=transcription.language_probability,
        progress_percent=transcription.progress_percent,
        segment_count=_segment_count(db, transcription),
        is_stale=is_stale(transcription, get_settings()),
        error_code=transcription.error_code,
        error_message=transcription.error_message,
        created_at=transcription.created_at,
        started_at=transcription.started_at,
        completed_at=transcription.completed_at,
    )


def _enqueue_or_503(db: DbSession, transcription: Transcription, *, created: bool) -> None:
    try:
        transcription.celery_task_id = enqueue_transcription(transcription.id)
    except JobQueueUnavailable:
        if created:
            db.delete(transcription)  # never leave a row that no worker will pick up
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The transcription queue is unavailable. Try again in a moment.",
        ) from None
    db.commit()


@router.post("/transcription", response_model=TranscriptionRead)
def start_transcription(video: OwnedVideo, db: DbSession, response_status: None = None):
    """Queue a transcription. Idempotent: an existing job is returned instead of duplicated."""
    existing = video.transcription
    if existing is not None:
        if existing.status == TranscriptionStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last transcription failed; use the retry endpoint",
            )
        return _read(db, existing)  # queued, running or completed: nothing new to start

    if video.status != VideoStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The video must be ready before it can be transcribed",
        )

    settings = get_settings()
    transcription = Transcription(
        video=video,
        provider=settings.transcription_provider,
        model=_configured_model(settings.transcription_provider),
    )
    db.add(transcription)
    db.commit()
    _enqueue_or_503(db, transcription, created=True)
    return _read(db, transcription)


@router.get("/transcription", response_model=TranscriptionRead)
def get_transcription(video: OwnedVideo, db: DbSession) -> TranscriptionRead:
    if video.transcription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No transcription yet")
    return _read(db, video.transcription)


@router.post("/transcription/retry", response_model=TranscriptionRead)
def retry_transcription(video: OwnedVideo, db: DbSession) -> TranscriptionRead:
    """Re-queue a failed or stale transcription. Live or completed jobs are not restarted."""
    transcription = video.transcription
    if transcription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No transcription yet")
    if transcription.status != TranscriptionStatus.FAILED and not is_stale(
        transcription, get_settings()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled transcription can be retried",
        )
    if video.status != VideoStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The video must be ready before it can be transcribed",
        )
    transcription.status = TranscriptionStatus.QUEUED
    transcription.progress_percent = 0
    transcription.error_code = None
    transcription.error_message = None
    transcription.started_at = None
    transcription.completed_at = None
    transcription.heartbeat_at = None
    db.commit()
    _enqueue_or_503(db, transcription, created=False)
    return _read(db, transcription)


@router.get("/transcript", response_model=TranscriptPage)
def get_transcript(
    video: OwnedVideo,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 200,
    include_text: bool = False,
) -> TranscriptPage:
    """A page of timestamped segments in sequence order; only for completed transcriptions."""
    transcription = video.transcription
    if transcription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No transcription yet")
    if transcription.status != TranscriptionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The transcript is not available while the transcription is {transcription.status}"
            ),
        )

    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_id == transcription.id)
        .order_by(TranscriptSegment.sequence_index)
        .offset(offset)
        .limit(limit)
    ).all()
    return TranscriptPage(
        transcription_id=transcription.id,
        total=_segment_count(db, transcription),
        offset=offset,
        limit=limit,
        segments=[
            TranscriptSegmentRead(
                sequence_index=s.sequence_index,
                start=s.start_time,
                end=s.end_time,
                text=s.text,
                speaker=s.speaker,
            )
            for s in segments
        ],
        full_text=transcription.full_text if include_text else None,
    )
