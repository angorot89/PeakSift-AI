"""Quick start: begin moment detection by itself once a transcript is ready.

The creator dropped one video on Home and asked for moments; nobody is there to press
"Find moments" when the transcript completes. This starts exactly one run with the server's
default provider — the first configured one that is reachable — and never more: a video that
already has a run (the creator started one, or this ran before) is left alone.

It never raises for an ordinary reason. No provider, an unusable transcript or a busy queue
simply mean no run was started; the project then shows the normal "Find moments" step.
"""

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    ClipDetectionRun,
    TranscriptionStatus,
    TranscriptSegment,
    Video,
    VideoStatus,
)
from app.services.clip_detection.contract import TranscriptLine
from app.services.clip_detection.detection_config import DetectionConfig
from app.services.clip_detection.factory import get_clip_provider, provider_options
from app.services.clip_detection.windowing import (
    TranscriptError,
    prepare_lines,
    transcript_fingerprint,
)
from app.workers.dispatch import JobQueueUnavailable, enqueue_clip_detection, new_task_id

logger = logging.getLogger(__name__)


def _reachable(name: str, model: str, settings: Settings) -> bool:
    """Whether the provider answers right now. Any problem counts as "no"."""
    try:
        return bool(get_clip_provider(name, model, settings).check_availability().available)
    except Exception:
        return False


def default_choice(
    settings: Settings, *, reachable: Callable[[str, str, Settings], bool] = _reachable
) -> tuple[str, str] | None:
    """The (provider, model) a creator gets without choosing: the first configured provider,
    in display order, that is reachable now. Starting a run on a provider that is switched
    off would only hand the creator a failure they did not ask for."""
    for option in provider_options(settings):
        if (
            option.configured
            and option.default_model
            and reachable(option.name, option.default_model, settings)
        ):
            return option.name, option.default_model
    return None


def start_default_detection(
    db: Session,
    video: Video,
    settings: Settings | None = None,
    *,
    reachable: Callable[[str, str, Settings], bool] = _reachable,
) -> ClipDetectionRun | None:
    """Queue the video's first detection run, or return None when there is nothing to start."""
    settings = settings or get_settings()
    transcription = video.transcription
    if (
        video.status != VideoStatus.READY
        or transcription is None
        or transcription.status != TranscriptionStatus.COMPLETED
    ):
        return None
    already = db.scalar(
        select(ClipDetectionRun.id).where(ClipDetectionRun.video_id == video.id).limit(1)
    )
    if already is not None:
        return None
    choice = default_choice(settings, reachable=reachable)
    if choice is None:
        logger.info("Quick start: no moment provider is reachable; video %s waits", video.id)
        return None

    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_id == transcription.id)
        .order_by(TranscriptSegment.sequence_index)
    )
    try:
        lines = prepare_lines(
            (TranscriptLine(s.start_time, s.end_time, s.text) for s in segments),
            video_duration=float(video.duration_seconds or 0.0),
            tolerance_seconds=settings.transcription_timestamp_tolerance_seconds,
        )
    except TranscriptError as error:
        logger.info("Quick start: transcript of video %s is not usable: %s", video.id, error.code)
        return None

    provider, model = choice
    run = ClipDetectionRun(
        video=video,
        transcription=transcription,
        transcript_fingerprint=transcript_fingerprint(transcription.id, lines),
        provider=provider,
        model=model,
        config=DetectionConfig.from_settings(settings).as_dict(),
        celery_task_id=new_task_id(),  # fencing token committed before the job exists
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:  # the creator started a run at the same moment; theirs stands
        db.rollback()
        return None
    try:
        enqueue_clip_detection(run.id, task_id=run.celery_task_id)
    except JobQueueUnavailable:
        db.delete(run)  # never leave a queued row that no worker will pick up
        db.commit()
        logger.warning("Quick start: the job queue was unavailable for video %s", video.id)
        return None
    return run
