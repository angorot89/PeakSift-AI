"""The smart-reframing job: clip → sampled frames → face detections → tracks → crop path.

Runs in a Celery worker (``peaksift.analyze_reframe``, ids only through the broker). The
``reframe_analyses`` row is the source of truth:

- **Claiming:** a completed analysis is never re-run; a live one (fresh heartbeat) is not run
  twice; a failed one runs again only after the retry endpoint resets it; a row whose task
  id belongs to a newer attempt is ignored.
- **Ownership:** the task id committed before enqueueing is the attempt token. Every commit
  and the failure path re-read it, so a stalled worker that a retry took over never writes the
  row (or its keyframes). A row deleted mid-run (its clip/video/project removed) stops the job.
- **Transactional result:** the whole path is computed in memory and validated, then the
  keyframes, statistics and ``completed`` are written in ONE commit. ``completed`` therefore
  always means a valid path exists; a failure leaves no partial path.
- **Honest progress:** 5 claimed (sampling), 10 → 80 detection (frames analysed / expected
  frames), 85 tracking, 92 planning, 100 completed.

There is no temporary workspace: frames stream from FFmpeg through a pipe (see
``sampling.py``), so nothing is left on disk by a crash, a timeout or a takeover.

Failure policy: a broken detector (``detector_unavailable`` / ``detector_failed``) fails the
analysis — it is never reported as "no face found". A clip with no faces is a successful
analysis with a centre-fallback path.
"""

import logging
import math
import uuid
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ClipStatus, ReframeAnalysis, ReframeKeyframe, ReframeStatus
from app.services.reframe.config import ReframeConfig
from app.services.reframe.detection import (
    DetectorFailure,
    DetectorUnavailable,
    SubjectDetection,
    SubjectDetectionProvider,
    get_detector,
)
from app.services.reframe.path import CropPlan, PlannedKeyframe, plan_crop_path
from app.services.reframe.sampling import (
    SamplingError,
    expected_samples,
    probe_geometry,
    sample_frames,
)
from app.services.reframe.tracking import track_subjects
from app.services.storage import InvalidStorageKey, LocalMediaStorage

logger = logging.getLogger(__name__)

SAMPLING_PROGRESS = 5
DETECTION_START = 10
DETECTION_END = 80
TRACKING_PROGRESS = 85
PLANNING_PROGRESS = 92
MAX_ERROR_LENGTH = 500


class PipelineSuperseded(Exception):
    """A newer attempt owns this analysis (or the row is gone); stop without writing."""


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(analysis: ReframeAnalysis, settings: Settings, *, now: datetime | None = None) -> bool:
    active = (
        ReframeStatus.SAMPLING,
        ReframeStatus.DETECTING,
        ReframeStatus.TRACKING,
        ReframeStatus.PLANNING,
    )
    if analysis.status not in active:
        return False
    last = analysis.heartbeat_at or analysis.started_at or analysis.created_at
    return ((now or _now()) - last).total_seconds() > settings.reframe_stale_after_seconds


def run_reframe_analysis(
    analysis_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: LocalMediaStorage | None = None,
    detector: SubjectDetectionProvider | None = None,
    task_id: str | None = None,
) -> ReframeAnalysis | None:
    """Analyse one ``ReframeAnalysis`` row. Problems are recorded, never raised."""
    settings = settings or get_settings()
    storage = storage or LocalMediaStorage(settings.media_root)
    analysis = db.get(ReframeAnalysis, analysis_id)
    if analysis is None:
        logger.warning("Reframe analysis %s no longer exists; nothing to do", analysis_id)
        return None
    if not _claim(analysis, db, settings, task_id):
        return analysis

    def fail(code: str, message: str) -> None:
        try:
            _fail(analysis, db, code, message, task_id=task_id)
        except Exception:
            # The database itself is failing: leave the row to go stale; retry recovers it.
            logger.exception("Could not record the failure of reframe analysis %s", analysis_id)
            db.rollback()

    try:
        _execute(analysis, db, settings, storage, detector, task_id)
    except PipelineSuperseded:
        logger.info("Reframe analysis %s was taken over or removed; stopping", analysis_id)
    except (PipelineFailure, SamplingError) as error:
        fail(error.code, error.message)
    except (DetectorUnavailable, DetectorFailure) as error:
        fail(error.code, error.message)
    except SoftTimeLimitExceeded:
        fail("time_limit", "Framing analysis ran longer than the worker allows; retry it")
    except Exception:
        logger.exception("Unexpected error analysing reframe %s", analysis_id)
        fail("internal_error", "Unexpected error while analysing the framing")
    return analysis


# --- claiming -----------------------------------------------------------------------------


def _claim(analysis: ReframeAnalysis, db: Session, settings: Settings, task_id: str | None) -> bool:
    if task_id and analysis.celery_task_id and analysis.celery_task_id != task_id:
        logger.info("Reframe analysis %s belongs to a newer attempt; ignoring", analysis.id)
        return False
    if analysis.status == ReframeStatus.COMPLETED:
        logger.info(
            "Reframe analysis %s is already completed; ignoring duplicate task", analysis.id
        )
        return False
    if analysis.status == ReframeStatus.FAILED:
        logger.info("Reframe analysis %s is failed; a retry must reset it first", analysis.id)
        return False
    if analysis.status != ReframeStatus.QUEUED and not is_stale(analysis, settings):
        logger.info("Reframe analysis %s is already running elsewhere", analysis.id)
        return False
    now = _now()
    db.execute(delete(ReframeKeyframe).where(ReframeKeyframe.reframe_analysis_id == analysis.id))
    analysis.status = ReframeStatus.SAMPLING
    analysis.progress_percent = SAMPLING_PROGRESS
    analysis.started_at = analysis.heartbeat_at = now
    analysis.completed_at = None
    analysis.error_code = analysis.error_message = None
    analysis.overall_confidence = analysis.confidence_level = None
    analysis.frames_sampled = analysis.detections_count = analysis.tracks_count = None
    analysis.subject_switches = analysis.fallback_fraction = None
    db.commit()
    return True


# --- the work -------------------------------------------------------------------------------


def _execute(
    analysis: ReframeAnalysis,
    db: Session,
    settings: Settings,
    storage: LocalMediaStorage,
    detector: SubjectDetectionProvider | None,
    task_id: str | None,
) -> None:
    try:
        config = ReframeConfig.from_snapshot(analysis.config)
    except ValueError:
        raise PipelineFailure(
            "invalid_configuration", "The framing configuration is not supported"
        ) from None
    clip = analysis.clip
    if clip.status != ClipStatus.READY or not clip.storage_key:
        raise PipelineFailure("clip_not_ready", "The source clip is not ready")
    try:
        source = storage.path_for(clip.storage_key)
    except InvalidStorageKey:
        raise PipelineFailure("clip_missing", "The source clip file is missing") from None
    if not source.is_file():
        raise PipelineFailure("clip_missing", "The source clip file is missing")

    geometry = probe_geometry(source, ffprobe_path=settings.ffprobe_path)
    analysis.source_width, analysis.source_height = geometry.width, geometry.height
    _heartbeat(analysis, db, task_id)

    # Fail fast on a broken detector, before decoding anything.
    provider = detector or get_detector(settings)
    analysis.provider, analysis.provider_version = provider.name, provider.version
    analysis.status = ReframeStatus.DETECTING
    analysis.progress_percent = DETECTION_START
    _heartbeat(analysis, db, task_id)

    total = expected_samples(geometry.duration_seconds, config.sample_fps)
    frames: list[tuple[float, list[SubjectDetection]]] = []
    detections = 0
    stream = sample_frames(
        source,
        geometry,
        ffmpeg_path=settings.ffmpeg_path,
        sample_fps=config.sample_fps,
        analysis_width=config.analysis_width,
        timeout_seconds=settings.reframe_sampling_timeout_seconds,
        heartbeat=lambda: _heartbeat(analysis, db, task_id),
        heartbeat_interval_seconds=settings.reframe_heartbeat_seconds,
    )
    with closing(stream):  # any error (detector, takeover) stops FFmpeg immediately
        for frame in stream:
            found = provider.detect(frame)
            frames.append((frame.timestamp, found))
            detections += len(found)
            progress = DETECTION_START + (DETECTION_END - DETECTION_START) * min(
                1.0, len(frames) / total
            )
            if int(progress) > analysis.progress_percent:
                analysis.progress_percent = int(progress)
                _heartbeat(analysis, db, task_id)

    analysis.status = ReframeStatus.TRACKING
    analysis.progress_percent = TRACKING_PROGRESS
    _heartbeat(analysis, db, task_id)
    tracking = track_subjects(
        frames, max_gap=config.max_gap_seconds, sample_period=1 / config.sample_fps
    )

    analysis.status = ReframeStatus.PLANNING
    analysis.progress_percent = PLANNING_PROGRESS
    _heartbeat(analysis, db, task_id)
    plan = plan_crop_path(
        tracking.samples,
        source_width=geometry.width,
        source_height=geometry.height,
        duration=geometry.duration_seconds,
        config=config,
        switches=tracking.switches,
    )
    validate_keyframes(plan.keyframes, geometry.duration_seconds)

    # One transaction: replace the path, record the results, mark completed.
    _ensure_still_owner(analysis, db, task_id)
    _finalize(
        analysis,
        db,
        plan,
        frames_sampled=len(frames),
        detections=detections,
        tracks=len(tracking.tracks),
    )
    _heartbeat(analysis, db, task_id)
    logger.info(
        "Reframe analysis %s completed: %d frames, %d detections, %d tracks, %d keyframes, "
        "%d camera cuts, %s",
        analysis.id,
        len(frames),
        detections,
        len(tracking.tracks),
        len(plan.keyframes),
        plan.camera_cuts,
        plan.confidence_level.value,
    )


def validate_keyframes(keyframes: Sequence[PlannedKeyframe], duration: float) -> None:
    """Every point finite, ordered, inside the source and the clip. Raises PipelineFailure."""
    if not keyframes:
        raise PipelineFailure("invalid_path", "The framing path is empty")
    previous = -1.0
    for k in keyframes:
        values = (k.timestamp, k.center_x, k.center_y, k.crop_width, k.crop_height, k.confidence)
        if not all(isinstance(v, int | float) and math.isfinite(v) for v in values):
            raise PipelineFailure("invalid_path", "The framing path contains invalid numbers")
        if k.timestamp < 0 or k.timestamp <= previous or k.timestamp > duration + 1e-6:
            raise PipelineFailure("invalid_path", "The framing path is not ordered within the clip")
        if not (0 < k.crop_width <= 1 and 0 < k.crop_height <= 1 and 0 <= k.confidence <= 1):
            raise PipelineFailure("invalid_path", "The framing path has an invalid crop")
        if (
            k.center_x - k.crop_width / 2 < -1e-6
            or k.center_x + k.crop_width / 2 > 1 + 1e-6
            or k.center_y - k.crop_height / 2 < -1e-6
            or k.center_y + k.crop_height / 2 > 1 + 1e-6
        ):
            raise PipelineFailure("invalid_path", "The framing path leaves the source frame")
        previous = k.timestamp


def _finalize(
    analysis: ReframeAnalysis,
    db: Session,
    plan: CropPlan,
    *,
    frames_sampled: int,
    detections: int,
    tracks: int,
) -> None:
    db.execute(delete(ReframeKeyframe).where(ReframeKeyframe.reframe_analysis_id == analysis.id))
    db.add_all(
        ReframeKeyframe(
            reframe_analysis_id=analysis.id,
            sequence_index=index,
            timestamp=k.timestamp,
            center_x=min(1.0, max(0.0, k.center_x)),
            center_y=min(1.0, max(0.0, k.center_y)),
            crop_width=k.crop_width,
            crop_height=k.crop_height,
            confidence=k.confidence,
            mode=k.mode.value,
        )
        for index, k in enumerate(plan.keyframes)
    )
    analysis.overall_confidence = plan.overall_confidence
    analysis.confidence_level = plan.confidence_level.value
    analysis.fallback_fraction = plan.fallback_fraction
    analysis.subject_switches = plan.subject_switches
    analysis.frames_sampled = frames_sampled
    analysis.detections_count = detections
    analysis.tracks_count = tracks
    analysis.status = ReframeStatus.COMPLETED
    analysis.progress_percent = 100
    analysis.completed_at = _now()


# --- state helpers ----------------------------------------------------------------------------


def _key(analysis: ReframeAnalysis) -> uuid.UUID:
    """The primary key without a database round trip (safe if the row was deleted)."""
    return sa_inspect(analysis).identity[0]


def _still_owner(analysis: ReframeAnalysis, db: Session, task_id: str | None) -> bool:
    with db.no_autoflush:  # read the committed token; never flush pending progress first
        row = db.execute(
            select(ReframeAnalysis.celery_task_id).where(ReframeAnalysis.id == _key(analysis))
        ).first()
    if row is None:
        return False
    if task_id is None:
        return True
    return not row.celery_task_id or row.celery_task_id == task_id


def _ensure_still_owner(analysis: ReframeAnalysis, db: Session, task_id: str | None) -> None:
    if not _still_owner(analysis, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(analysis: ReframeAnalysis, db: Session, task_id: str | None = None) -> None:
    """Commit progress — but only while this attempt still owns the analysis."""
    _ensure_still_owner(analysis, db, task_id)
    analysis.heartbeat_at = _now()
    db.commit()


def _fail(
    analysis: ReframeAnalysis, db: Session, code: str, message: str, *, task_id: str | None = None
) -> None:
    db.rollback()
    analysis_id = _key(analysis)
    if not _still_owner(analysis, db, task_id):
        logger.info(
            "Reframe analysis %s failed (%s) after being taken over; ignoring", analysis_id, code
        )
        return
    db.execute(delete(ReframeKeyframe).where(ReframeKeyframe.reframe_analysis_id == analysis_id))
    analysis.status = ReframeStatus.FAILED
    analysis.error_code = code[:64]
    analysis.error_message = message[:MAX_ERROR_LENGTH]
    analysis.completed_at = _now()
    analysis.heartbeat_at = analysis.completed_at
    db.commit()
    logger.warning("Reframe analysis %s failed: %s — %s", analysis_id, code, message)
