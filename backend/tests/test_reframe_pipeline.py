"""The background reframe analysis: real FFmpeg sampling of a generated clip, a scripted
detector (no model), the database as source of truth, attempt ownership and transactions."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kombu.exceptions import OperationalError
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ReframeAnalysis, ReframeKeyframe, ReframeStatus
from app.services.clip_render.storage import clip_storage_key
from app.services.reframe import pipeline
from app.services.reframe.detection import (
    BoundingBox,
    DetectionType,
    DetectorFailure,
    DetectorUnavailable,
    SubjectDetection,
)
from app.services.reframe.pipeline import is_stale, run_reframe_analysis
from app.services.storage import LocalMediaStorage
from app.workers import dispatch
from app.workers.celery_app import celery_app
from app.workers.dispatch import JobQueueUnavailable, enqueue_reframe_analysis, new_task_id
from tests.media_fixtures import generate_video, requires_ffmpeg
from tests.test_clip_edit_model import make_clip
from tests.test_reframe_model import make_analysis

pytestmark = requires_ffmpeg
CLIP_SECONDS = 4.0


@pytest.fixture
def settings() -> Settings:
    return Settings(**get_settings().model_dump())


@pytest.fixture
def storage() -> LocalMediaStorage:
    return LocalMediaStorage(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalMediaStorage):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


def ready_analysis(db: Session, storage: LocalMediaStorage, *, with_file=True) -> ReframeAnalysis:
    clip = make_clip(db)
    clip.storage_key = clip_storage_key(clip.id)
    db.commit()
    if with_file:
        path = storage.path_for(clip.storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        generate_video(path, seconds=CLIP_SECONDS, audio=False)  # 64x64 test pattern
    return make_analysis(db, clip)


class ScriptedDetector:
    """A face moving left → right; can fail at a timestamp or run a hook mid-analysis."""

    name, version = "yunet_face", "test-double"

    def __init__(self, *, fail_at=None, error=None, on_frame=None, faces=True):
        self.calls, self.fail_at, self.error, self.on_frame, self.faces = (
            [],
            fail_at,
            error,
            on_frame,
            faces,
        )

    def detect(self, frame):
        self.calls.append(frame.timestamp)
        if self.on_frame:
            self.on_frame(frame.timestamp)
        if self.fail_at is not None and frame.timestamp >= self.fail_at:
            raise self.error or DetectorFailure()
        if not self.faces:
            return []
        cx = 0.2 + 0.1 * frame.timestamp
        return [
            SubjectDetection(
                frame.timestamp, DetectionType.FACE, 0.9, BoundingBox(cx - 0.03, 0.3, 0.06, 0.12)
            )
        ]


def run(analysis, db, settings, storage, detector, task_id="task-1"):
    return run_reframe_analysis(
        analysis.id, db, settings=settings, storage=storage, detector=detector, task_id=task_id
    )


def keyframes(db, analysis_id):
    return db.scalars(
        select(ReframeKeyframe)
        .where(ReframeKeyframe.reframe_analysis_id == analysis_id)
        .order_by(ReframeKeyframe.sequence_index)
    ).all()


# --- success -----


def test_successful_analysis_persists_a_valid_path_and_statistics(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    detector = ScriptedDetector()
    result = run(analysis, db_session, settings, storage, detector)
    assert result.status == ReframeStatus.COMPLETED and result.progress_percent == 100
    assert (result.source_width, result.source_height) == (64, 64)
    assert result.frames_sampled == 8 == len(detector.calls) and result.detections_count == 8
    assert (
        result.tracks_count == 1 and result.subject_switches == 0 and result.fallback_fraction == 0
    )
    assert result.confidence_level in ("high", "mixed") and 0 < result.overall_confidence <= 1
    assert result.provider == "yunet_face" and result.provider_version == "test-double"
    points = keyframes(db_session, analysis.id)
    assert points and [p.sequence_index for p in points] == list(range(len(points)))
    assert points[0].timestamp == 0 and points[-1].timestamp == pytest.approx(CLIP_SECONDS, abs=0.1)
    assert result.completed_at is not None and result.error_code is None


def test_a_clip_without_faces_is_a_successful_centre_fallback(db_session, settings, storage):
    result = run(
        ready_analysis(db_session, storage),
        db_session,
        settings,
        storage,
        ScriptedDetector(faces=False),
    )
    assert result.status == ReframeStatus.COMPLETED and result.confidence_level == "fallback"
    assert result.fallback_fraction == 1 and result.detections_count == 0
    assert {p.mode for p in keyframes(db_session, result.id)} == {"fallback"}


def test_progress_is_honest_and_monotonic(monkeypatch, db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    seen = []
    real = pipeline._heartbeat

    def spy(row, db, task_id=None):
        real(row, db, task_id)
        seen.append((row.status, row.progress_percent))

    monkeypatch.setattr(pipeline, "_heartbeat", spy)
    run(analysis, db_session, settings, storage, ScriptedDetector())
    progress = [p for _, p in seen]
    assert progress == sorted(progress) and progress[-1] == 100
    statuses = [s for s, _ in seen]
    assert (
        statuses.index("detecting")
        < statuses.index("tracking")
        < statuses.index("planning")
        < statuses.index("completed")
    )
    detecting = [p for s, p in seen if s == "detecting"]
    assert min(detecting) == 10 and max(detecting) == 80


# --- failures -----


def test_detector_unavailable_fails_clearly_not_as_no_face(db_session, settings, storage):
    detector = ScriptedDetector(
        fail_at=0, error=DetectorUnavailable("The face detector model is not installed")
    )
    result = run(ready_analysis(db_session, storage), db_session, settings, storage, detector)
    assert result.status == ReframeStatus.FAILED and result.error_code == "detector_unavailable"
    assert keyframes(db_session, result.id) == []


def test_detector_crash_midway_leaves_no_partial_path(db_session, settings, storage):
    result = run(
        ready_analysis(db_session, storage),
        db_session,
        settings,
        storage,
        ScriptedDetector(fail_at=2.0),
    )
    assert result.status == ReframeStatus.FAILED and result.error_code == "detector_failed"
    assert keyframes(db_session, result.id) == [] and result.overall_confidence is None


def test_missing_clip_file_is_reported(db_session, settings, storage):
    result = run(
        ready_analysis(db_session, storage, with_file=False),
        db_session,
        settings,
        storage,
        ScriptedDetector(),
    )
    assert result.status == ReframeStatus.FAILED and result.error_code == "clip_missing"


def test_unreadable_clip_is_reported(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage, with_file=False)
    path = storage.path_for(analysis.clip.storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a video at all" * 100)
    result = run(analysis, db_session, settings, storage, ScriptedDetector())
    assert result.status == ReframeStatus.FAILED and result.error_code == "source_unreadable"
    assert str(storage.root) not in result.error_message


def test_clip_not_ready_is_reported(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    analysis.clip.status = "rendering"
    db_session.commit()
    assert (
        run(analysis, db_session, settings, storage, ScriptedDetector()).error_code
        == "clip_not_ready"
    )


def test_unexpected_errors_are_generic_and_path_free(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    result = run(
        analysis,
        db_session,
        settings,
        storage,
        ScriptedDetector(fail_at=0, error=RuntimeError(f"boom {storage.root}")),
    )
    assert result.error_code == "internal_error" and str(storage.root) not in result.error_message


def test_transaction_failure_at_finalize_never_exposes_a_completed_path(
    monkeypatch, db_session, settings, storage
):
    analysis = ready_analysis(db_session, storage)
    real = pipeline._finalize

    def explode(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("database went away during commit")

    monkeypatch.setattr(pipeline, "_finalize", explode)
    result = run(analysis, db_session, settings, storage, ScriptedDetector())
    db_session.expire_all()
    row = db_session.get(ReframeAnalysis, result.id)
    assert row.status == ReframeStatus.FAILED and keyframes(db_session, row.id) == []


def test_invalid_planned_keyframes_are_refused(monkeypatch, db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    real = pipeline.plan_crop_path

    def broken(*args, **kwargs):
        plan = real(*args, **kwargs)
        bad = plan.keyframes[0].__class__(
            **{**plan.keyframes[0].__dict__, "center_x": float("nan")}
        )
        return plan.__class__(**{**plan.__dict__, "keyframes": [bad, *plan.keyframes[1:]]})

    monkeypatch.setattr(pipeline, "plan_crop_path", broken)
    result = run(analysis, db_session, settings, storage, ScriptedDetector())
    assert result.status == ReframeStatus.FAILED and result.error_code == "invalid_path"


# --- idempotency and ownership -----


def test_completed_analysis_ignores_duplicate_delivery(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    run(analysis, db_session, settings, storage, ScriptedDetector())
    before = [(k.timestamp, k.center_x) for k in keyframes(db_session, analysis.id)]
    again = ScriptedDetector()
    run(analysis, db_session, settings, storage, again)
    assert (
        again.calls == []
        and [(k.timestamp, k.center_x) for k in keyframes(db_session, analysis.id)] == before
    )


def test_failed_analysis_needs_an_explicit_retry(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    run(analysis, db_session, settings, storage, ScriptedDetector(fail_at=0))
    again = ScriptedDetector()
    assert (
        run(analysis, db_session, settings, storage, again).status == ReframeStatus.FAILED
        and again.calls == []
    )
    # what the retry endpoint does: new attempt, new token, queued
    analysis.status, analysis.attempt, analysis.celery_task_id = ReframeStatus.QUEUED, 2, "task-2"
    db_session.commit()
    assert (
        run(analysis, db_session, settings, storage, again, task_id="task-2").status
        == ReframeStatus.COMPLETED
    )


def test_live_analysis_is_not_run_twice_but_a_stale_one_is_reclaimed(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    analysis.status, analysis.heartbeat_at = ReframeStatus.DETECTING, datetime.now(UTC)
    db_session.commit()
    busy = ScriptedDetector()
    run(analysis, db_session, settings, storage, busy)
    assert busy.calls == [] and not is_stale(analysis, settings)
    analysis.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.reframe_stale_after_seconds + 5
    )
    db_session.commit()
    assert is_stale(analysis, settings)
    assert (
        run(analysis, db_session, settings, storage, ScriptedDetector()).status
        == ReframeStatus.COMPLETED
    )


def _take_over(db, analysis_id):
    db.execute(
        update(ReframeAnalysis)
        .where(ReframeAnalysis.id == analysis_id)
        .values(celery_task_id="task-2", attempt=2, status=ReframeStatus.QUEUED, progress_percent=0)
    )
    db.commit()


def test_stalled_worker_cannot_write_after_a_retry_took_over(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    analysis_id = analysis.id
    hooked = {"done": False}

    def take_over_once(t):
        if t >= 1.0 and not hooked["done"]:
            hooked["done"] = True
            _take_over(db_session, analysis_id)

    run(analysis, db_session, settings, storage, ScriptedDetector(on_frame=take_over_once))
    db_session.expire_all()
    row = db_session.get(ReframeAnalysis, analysis_id)
    assert (
        row.celery_task_id == "task-2"
        and row.status == ReframeStatus.QUEUED
        and row.progress_percent == 0
    )
    assert row.error_code is None and keyframes(db_session, analysis_id) == []


def test_resumed_old_worker_cannot_touch_the_new_attempts_result(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    _take_over(db_session, analysis.id)
    run(
        analysis, db_session, settings, storage, ScriptedDetector(), task_id="task-2"
    )  # attempt 2 completes
    db_session.expire_all()
    done = [(k.timestamp, k.center_x) for k in keyframes(db_session, analysis.id)]
    old = ScriptedDetector()
    run(analysis, db_session, settings, storage, old, task_id="task-1")  # the old worker wakes up
    db_session.expire_all()
    assert (
        old.calls == []
        and db_session.get(ReframeAnalysis, analysis.id).status == ReframeStatus.COMPLETED
    )
    assert [(k.timestamp, k.center_x) for k in keyframes(db_session, analysis.id)] == done


def test_analysis_deleted_mid_run_stops_quietly(db_session, settings, storage):
    analysis = ready_analysis(db_session, storage)
    analysis_id = analysis.id

    def delete_row(t):
        if t >= 1.0:
            db_session.execute(delete(ReframeAnalysis).where(ReframeAnalysis.id == analysis_id))
            db_session.commit()

    run(analysis, db_session, settings, storage, ScriptedDetector(on_frame=delete_row))
    db_session.expire_all()
    assert db_session.get(ReframeAnalysis, analysis_id) is None


def test_unknown_analysis_is_a_quiet_noop(db_session, settings, storage):
    assert (
        run_reframe_analysis(uuid.uuid4(), db_session, settings=settings, storage=storage) is None
    )


# --- Celery task and dispatch -----


class _Reusable:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


def test_task_is_registered_and_runs_the_pipeline_eagerly(
    monkeypatch, db_session, settings, storage
):
    assert "peaksift.analyze_reframe" in celery_app.tasks
    analysis = ready_analysis(db_session, storage)
    token = new_task_id()
    analysis.celery_task_id = token
    db_session.commit()
    monkeypatch.setattr("app.workers.reframe_tasks.SessionLocal", lambda: _Reusable(db_session))
    monkeypatch.setattr("app.services.reframe.pipeline.get_detector", lambda s: ScriptedDetector())
    enqueue_reframe_analysis(analysis.id, task_id=token)
    db_session.expire_all()
    assert db_session.get(ReframeAnalysis, analysis.id).status == ReframeStatus.COMPLETED


def test_task_with_invalid_id_is_a_noop():
    celery_app.tasks["peaksift.analyze_reframe"].apply(args=["not-a-uuid"]).get()


def test_enqueue_when_broker_is_down(monkeypatch):
    def down(*args, **kwargs):
        raise OperationalError("redis down")

    monkeypatch.setattr(dispatch.analyze_reframe_task, "apply_async", down)
    with pytest.raises(JobQueueUnavailable):
        enqueue_reframe_analysis(uuid.uuid4(), task_id="t")
