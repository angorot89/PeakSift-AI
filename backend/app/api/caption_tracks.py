"""Word timing for a generated clip's captions: start (idempotent per server configuration),
list, current, status, words, retry — plus the timing options the editor can offer.

Ownership chain: User → Project → Video → Clip → CaptionTrack; anything else is a 404 (401
without a session). A request can only ask "time the words of this clip": the provider,
model and every option are server configuration, captured in a snapshot whose fingerprint
makes ``(clip_id, config_fingerprint)`` unique — repeated clicks return the same track.
"""

import importlib.util
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.clip_edits import OwnedClip
from app.api.deps import DbSession, Storage
from app.core.config import Settings, get_settings
from app.models import (
    CaptionTrack,
    CaptionTrackStatus,
    CaptionWord,
    Clip,
    ClipStatus,
    TranscriptionStatus,
)
from app.schemas.caption_track import (
    CaptionTimingOptions,
    CaptionTrackPage,
    CaptionTrackRead,
    CaptionWordRead,
    CaptionWordsRead,
)
from app.services.caption_timing.config import CaptionTimingConfig
from app.services.caption_timing.pipeline import is_stale
from app.services.storage import InvalidStorageKey, LocalMediaStorage
from app.workers.dispatch import JobQueueUnavailable, enqueue_caption_track, new_task_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clips/{clip_id}", tags=["captions"]
)

MAX_LIST = 20
# A clip is at most a few minutes long; this bound only protects against absurd rows.
MAX_WORDS = 5000


def get_owned_track(track_id: uuid.UUID, clip: OwnedClip, db: DbSession) -> CaptionTrack:
    track = db.scalar(
        select(CaptionTrack).where(CaptionTrack.id == track_id, CaptionTrack.clip_id == clip.id)
    )
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caption track not found")
    return track


OwnedTrack = Annotated[CaptionTrack, Depends(get_owned_track)]


def _read(track: CaptionTrack) -> CaptionTrackRead:
    return CaptionTrackRead(
        id=track.id,
        clip_id=track.clip_id,
        status=track.status,
        progress_percent=track.progress_percent,
        attempt=track.attempt,
        is_stale=is_stale(track, get_settings()),
        provider=track.provider,
        model=track.model,
        language=track.language,
        word_count=track.word_count,
        rejected_word_count=track.rejected_word_count,
        average_confidence=track.average_confidence,
        error_code=track.error_code,
        error_message=track.error_message,
        created_at=track.created_at,
        started_at=track.started_at,
        completed_at=track.completed_at,
    )


def timing_available(settings: Settings) -> bool:
    """Whether the configured provider can run here — checked without importing or loading
    anything (no model is touched by the API process)."""
    if settings.caption_timing_provider == "faster_whisper":
        return importlib.util.find_spec("faster_whisper") is not None
    return False  # pragma: no cover - the setting is an allow-list


def _language_hint(clip: Clip) -> str | None:
    """The transcript's detected language steers the timing model when it is known."""
    transcription = clip.video.transcription
    if transcription is not None and transcription.status == TranscriptionStatus.COMPLETED:
        return transcription.language or None
    return None


def _config(clip: Clip) -> CaptionTimingConfig:
    return CaptionTimingConfig.from_settings(get_settings(), language_hint=_language_hint(clip))


def _current(db: DbSession, clip: Clip) -> CaptionTrack | None:
    fingerprint = _config(clip).fingerprint()
    return db.scalar(
        select(CaptionTrack).where(
            CaptionTrack.clip_id == clip.id, CaptionTrack.config_fingerprint == fingerprint
        )
    )


def _require_timeable(clip: Clip, storage: LocalMediaStorage) -> None:
    if clip.status != ClipStatus.READY or not clip.storage_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Generate the clip before timing captions"
        )
    try:
        present = storage.path_for(clip.storage_key).is_file()
    except InvalidStorageKey:
        present = False
    if not present:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The clip file is missing; generate the clip again",
        )
    if not timing_available(get_settings()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Word timing is not available on this server",
        )


def _enqueue_or_503(db: DbSession, track: CaptionTrack, *, created: bool) -> None:
    """The attempt token is already committed on the row; hand the job to the broker."""
    try:
        enqueue_caption_track(track.id, task_id=track.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(track)  # never leave a queued row that no worker will pick up
        else:
            track.status = CaptionTrackStatus.FAILED
            track.error_code = "queue_unavailable"
            track.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The caption timing queue is unavailable. Try again in a moment.",
        ) from None


@router.get("/caption-timing", response_model=CaptionTimingOptions)
def timing_options(clip: OwnedClip, db: DbSession) -> CaptionTimingOptions:
    """Word timing state for the current configuration, and whether phrase timing exists."""
    track = _current(db, clip)
    if track is None:
        word = "none"
    elif track.status == CaptionTrackStatus.COMPLETED:
        word = "completed"
    elif track.status == CaptionTrackStatus.FAILED:
        word = "failed"
    else:
        word = "running"
    transcription = clip.video.transcription
    phrase = transcription is not None and transcription.status == TranscriptionStatus.COMPLETED
    return CaptionTimingOptions(
        word_timing=word,
        track=_read(track) if track else None,
        phrase_timing_available=phrase,
    )


@router.post(
    "/caption-tracks", response_model=CaptionTrackRead, status_code=status.HTTP_201_CREATED
)
def start_track(clip: OwnedClip, db: DbSession, storage: Storage, response: Response):
    """Time the clip's words with the server's configuration. The same configuration returns
    the existing track (200); a failed one must be retried (409)."""
    config = _config(clip)
    fingerprint = config.fingerprint()
    existing = _current(db, clip)
    if existing is not None:
        if existing.status == CaptionTrackStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last word timing failed; use the retry endpoint",
            )
        response.status_code = status.HTTP_200_OK
        return _read(existing)

    _require_timeable(clip, storage)
    track = CaptionTrack(
        clip_id=clip.id,
        video_id=clip.video_id,
        provider=config.provider,
        model=config.model,
        alignment_version=config.alignment_version,
        config=config.snapshot(),
        config_fingerprint=fingerprint,
        language_hint=config.language_hint,
        celery_task_id=new_task_id(),  # attempt token committed before the job exists
    )
    db.add(track)
    try:
        db.commit()
    except IntegrityError:  # a concurrent identical request won the unique constraint
        db.rollback()
        winner = _current(db, clip)
        if winner is None:  # pragma: no cover - the other transaction vanished
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Try again") from None
        response.status_code = status.HTTP_200_OK
        return _read(winner)
    _enqueue_or_503(db, track, created=True)
    return _read(track)


@router.get("/caption-tracks", response_model=CaptionTrackPage)
def list_tracks(clip: OwnedClip, db: DbSession) -> CaptionTrackPage:
    """The clip's tracks, newest first (several exist only if the server config changed)."""
    total = (
        db.scalar(
            select(func.count()).select_from(CaptionTrack).where(CaptionTrack.clip_id == clip.id)
        )
        or 0
    )
    rows = db.scalars(
        select(CaptionTrack)
        .where(CaptionTrack.clip_id == clip.id)
        .order_by(CaptionTrack.created_at.desc(), CaptionTrack.id.desc())
        .limit(MAX_LIST)
    ).all()
    return CaptionTrackPage(total=total, tracks=[_read(r) for r in rows])


@router.get("/caption-tracks/current", response_model=CaptionTrackRead)
def current_track(clip: OwnedClip, db: DbSession) -> CaptionTrackRead:
    """The track for the server's current configuration (404 if none yet)."""
    track = _current(db, clip)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No word timing yet")
    return _read(track)


@router.get("/caption-tracks/{track_id}", response_model=CaptionTrackRead)
def get_track(track: OwnedTrack) -> CaptionTrackRead:
    return _read(track)


@router.get("/caption-tracks/{track_id}/words", response_model=CaptionWordsRead)
def get_words(track: OwnedTrack, db: DbSession) -> CaptionWordsRead:
    """The completed track's words in order (409 until the track has completed)."""
    if track.status != CaptionTrackStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The word timing is not complete"
        )
    rows = db.scalars(
        select(CaptionWord)
        .where(CaptionWord.caption_track_id == track.id)
        .order_by(CaptionWord.sequence_index)
        .limit(MAX_WORDS)
    ).all()
    return CaptionWordsRead(
        track_id=track.id,
        language=track.language,
        words=[
            CaptionWordRead(
                i=w.sequence_index,
                start=w.start_time,
                end=w.end_time,
                text=w.text,
                confidence=w.confidence,
            )
            for w in rows
        ],
    )


@router.post("/caption-tracks/{track_id}/retry", response_model=CaptionTrackRead)
def retry_track(
    track: OwnedTrack, clip: OwnedClip, db: DbSession, storage: Storage
) -> CaptionTrackRead:
    """Re-queue a failed or stalled track on the same row with a fresh attempt token."""
    settings = get_settings()
    # Lock the row until the commit below: concurrent retries serialize and the second sees
    # "queued" (409) instead of enqueueing a duplicate job.
    db.refresh(track, with_for_update=True)
    if track.status != CaptionTrackStatus.FAILED and not is_stale(track, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled word timing can be retried",
        )
    if track.attempt >= settings.caption_timing_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This word timing has been retried too many times",
        )
    _require_timeable(clip, storage)
    db.execute(delete(CaptionWord).where(CaptionWord.caption_track_id == track.id))
    track.status = CaptionTrackStatus.QUEUED
    track.progress_percent = 0
    track.attempt += 1
    track.error_code = track.error_message = None
    track.started_at = track.completed_at = track.heartbeat_at = None
    track.celery_task_id = new_task_id()  # fences out a stalled worker of the old attempt
    db.commit()
    _enqueue_or_503(db, track, created=False)
    return _read(track)
