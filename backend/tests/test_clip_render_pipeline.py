import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kombu.exceptions import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipStatus,
    Project,
    Transcription,
    TranscriptSegment,
    User,
    Video,
)
from app.services.clip_render import pipeline
from app.services.clip_render.pipeline import is_stale, run_clip_render
from app.services.clip_render.renderer import RenderedClip, RenderError
from app.services.clip_render.storage import ClipArtifactStore, clip_storage_key
from app.services.storage import LocalMediaStorage
from app.workers import dispatch
from app.workers.celery_app import celery_app
from app.workers.clip_render_tasks import render_clip_task
from app.workers.dispatch import JobQueueUnavailable, enqueue_clip_render, new_task_id
from tests.media_fixtures import generate_video, requires_ffmpeg

SOURCE_SECONDS = 6.0


@pytest.fixture
def settings() -> Settings:
    base = get_settings().model_dump()
    base.update(clip_render_preset="ultrafast", clip_render_timeout_seconds=120)
    return Settings(**base)


@pytest.fixture
def storage() -> LocalMediaStorage:
    return LocalMediaStorage(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalMediaStorage):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


@pytest.fixture
def clip(db_session: Session, storage: LocalMediaStorage, tmp_path: Path) -> Clip:
    """A queued clip for candidate [2, 4] of a real 6 s generated source video."""
    key = storage.generate_key("mp4")
    source_path = storage.path_for(key)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    if pipeline.render_clip is not None and _ffmpeg_available():
        generate_video(source_path, seconds=SOURCE_SECONDS)
    else:
        source_path.write_bytes(b"fake video")
    user = User(email="creator@example.com", password_hash="x")
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=key,
        content_type="video/mp4",
        file_size=source_path.stat().st_size,
        status="ready",
        duration_seconds=SOURCE_SECONDS,
    )
    transcription = Transcription(video=video, provider="fake", model="fake-1", status="completed")
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0.0, end_time=6.0, text="hello")
    )
    run = ClipDetectionRun(
        video=video,
        transcription=transcription,
        transcript_fingerprint="f" * 64,
        provider="ollama",
        model="llama3.2:3b",
        config={},
        status="completed",
    )
    db_session.add_all([user, video, transcription, run])
    db_session.flush()
    candidate = ClipCandidate(
        run=run,
        video_id=video.id,
        start_time=2.0,
        end_time=4.0,
        duration_seconds=2.0,
        title="The reveal",
        hook="h",
        rationale="r",
        category="story",
        transcript_excerpt="hello",
        overall_score=80,
        hook_score=80,
        entertainment_score=80,
        clarity_score=80,
        payoff_score=80,
        completeness_score=80,
        rank=1,
    )
    row = Clip(
        candidate=candidate,
        video_id=video.id,
        start_time=2.0,
        end_time=4.0,
        duration_seconds=2.0,
        celery_task_id="task-1",
    )
    db_session.add_all([candidate, row])
    db_session.commit()
    return row


def _ffmpeg_available() -> bool:
    from tests.media_fixtures import have_ffmpeg

    return have_ffmpeg()


def fake_rendered(path: Path, *, audio: str | None = "aac") -> RenderedClip:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 2048)
    return RenderedClip(
        path=path,
        size_bytes=2048,
        duration_seconds=2.0,
        width=64,
        height=64,
        fps=30.0,
        video_codec="h264",
        audio_codec=audio,
    )


class SpyRenderer:
    """A renderer that records the clip's state when called and can beat/fail on demand."""

    def __init__(self, db: Session, row: Clip, *, error: RenderError | None = None, beats=2):
        self.db, self.row, self.error, self.beats = db, row, error, beats
        self.calls: list[dict] = []
        self.observed: list[tuple[str, int]] = []

    def __call__(self, source, target, *, start, end, options, heartbeat=None):
        self.calls.append(
            {"source": source, "target": target, "start": start, "end": end, "options": options}
        )
        self.db.refresh(self.row)
        self.observed.append((self.row.status, self.row.progress_percent))
        for _ in range(self.beats):
            if heartbeat:
                heartbeat()
        if self.error:
            raise self.error
        return fake_rendered(target)


def execute(row, db, settings, storage, renderer, **kwargs) -> Clip:
    return run_clip_render(
        row.id,
        db,
        settings=settings,
        storage=storage,
        renderer=renderer,
        task_id=kwargs.pop("task_id", "task-1"),
        **kwargs,
    )


# --- happy path (real ffmpeg) -----


@requires_ffmpeg
def test_real_render_makes_the_clip_ready_with_validated_metadata(
    db_session, clip, settings, storage
):
    result = execute(clip, db_session, settings, storage, pipeline.render_clip)

    assert result.status == ClipStatus.READY and result.progress_percent == 100
    assert result.storage_key == clip_storage_key(clip.id)
    store = ClipArtifactStore(storage)
    assert store.exists(clip.id)
    assert not storage.path_for(f"clips/{clip.id}/clip-tmp-1.mp4").exists()
    assert result.file_size == store.final_path(clip.id).stat().st_size > 0
    assert (result.width, result.height) == (64, 64)
    assert result.video_codec == "h264" and result.audio_codec == "aac"
    assert result.fps and result.fps > 0
    assert result.started_at is not None and result.completed_at is not None
    assert result.error_code is None and result.error_message is None


# --- happy path (fake renderer) -----


def test_stages_and_progress_are_honest_and_monotonic(db_session, clip, settings, storage):
    renderer = SpyRenderer(db_session, clip)
    seen: list[tuple[str, int]] = []
    original_heartbeat = pipeline._heartbeat

    def spy_heartbeat(row, db, task_id=None):
        original_heartbeat(row, db, task_id)
        seen.append((row.status, row.progress_percent))

    pipeline._heartbeat = spy_heartbeat
    try:
        result = execute(clip, db_session, settings, storage, renderer)
    finally:
        pipeline._heartbeat = original_heartbeat

    assert renderer.observed == [("rendering", 10)]  # claimed and committed before ffmpeg
    progress = [p for _, p in seen]
    assert progress == sorted(progress) and progress[-1] == 100
    assert ("rendering", 80) in seen and ("validating", 90) in seen and ("ready", 100) in seen
    assert result.heartbeat_at is not None


def test_renderer_receives_the_snapshot_boundaries_and_settings(
    db_session, clip, settings, storage
):
    renderer = SpyRenderer(db_session, clip)
    execute(clip, db_session, settings, storage, renderer)
    (call,) = renderer.calls
    assert (call["start"], call["end"]) == (2.0, 4.0)
    assert call["source"] == storage.path_for(clip.video.storage_key)
    assert call["target"].name == "clip-tmp-1.mp4" and str(clip.id) in str(call["target"])
    assert call["options"].preset == "ultrafast" and call["options"].timeout_seconds == 120


def test_retry_discards_an_orphaned_final_artifact_first(db_session, clip, settings, storage):
    """DB said failed/queued but a final file was left behind: it must not leak into 'ready'."""
    store = ClipArtifactStore(storage)
    store.temp_path(clip.id).write_bytes(b"orphan")
    store.finalize(clip.id)
    assert store.exists(clip.id)

    result = execute(clip, db_session, settings, storage, SpyRenderer(db_session, clip))

    assert result.status == ClipStatus.READY
    assert (
        store.final_path(clip.id).read_bytes() == b"\x00" * 2048
    )  # the new render, not the orphan


# --- failures -----


def test_render_error_is_recorded_and_artifacts_removed(db_session, clip, settings, storage):
    renderer = SpyRenderer(
        db_session,
        clip,
        error=RenderError("render_timeout", "Rendering timed out after 1800 seconds"),
    )
    result = execute(clip, db_session, settings, storage, renderer)

    assert result.status == ClipStatus.FAILED
    assert result.error_code == "render_timeout" and "timed out" in result.error_message
    assert result.storage_key is None and result.completed_at is not None
    assert not storage.path_for(f"clips/{clip.id}/clip.mp4").parent.exists()


def test_missing_source_fails_safely(db_session, clip, settings, storage):
    storage.path_for(clip.video.storage_key).unlink()
    result = execute(clip, db_session, settings, storage, SpyRenderer(db_session, clip))
    assert result.status == ClipStatus.FAILED and result.error_code == "source_missing"
    assert "/" not in result.error_message


def test_video_not_ready_fails_safely(db_session, clip, settings, storage):
    clip.video.status = "failed"
    db_session.commit()
    renderer = SpyRenderer(db_session, clip)
    result = execute(clip, db_session, settings, storage, renderer)
    assert result.status == ClipStatus.FAILED and result.error_code == "video_not_ready"
    assert renderer.calls == []


def test_renderer_output_vanishing_before_finalize_is_a_storage_failure(
    db_session, clip, settings, storage
):
    def vanishing(source, target, *, start, end, options, heartbeat=None):
        rendered = fake_rendered(target)
        target.unlink()  # disk problem between validation and finalize
        return rendered

    result = execute(clip, db_session, settings, storage, vanishing)
    assert result.status == ClipStatus.FAILED and result.error_code == "storage_failure"


def test_unexpected_exception_is_generic_and_path_free(db_session, clip, settings, storage):
    def explode(*args, **kwargs):
        raise RuntimeError(f"disk on fire at {storage.root}")

    result = execute(clip, db_session, settings, storage, explode)
    assert result.status == ClipStatus.FAILED and result.error_code == "internal_error"
    assert str(storage.root) not in result.error_message


def test_soft_time_limit_is_an_honest_failure(db_session, clip, settings, storage):
    from celery.exceptions import SoftTimeLimitExceeded

    def slow(*args, **kwargs):
        raise SoftTimeLimitExceeded()

    result = execute(clip, db_session, settings, storage, slow)
    assert result.status == ClipStatus.FAILED and result.error_code == "time_limit"


def test_failure_never_touches_source_candidate_or_transcript(db_session, clip, settings, storage):
    source = storage.path_for(clip.video.storage_key)
    before = source.read_bytes()
    execute(
        clip,
        db_session,
        settings,
        storage,
        SpyRenderer(db_session, clip, error=RenderError("ffmpeg_failed", "x")),
    )
    db_session.expire_all()
    video = db_session.get(Video, clip.video_id)
    assert source.read_bytes() == before
    assert video.status == "ready"
    assert db_session.get(ClipCandidate, clip.candidate_id).title == "The reveal"
    assert video.transcription.status == "completed" and len(video.transcription.segments) == 1


# --- idempotency and fencing -----


def test_ready_clip_ignores_duplicate_delivery(db_session, clip, settings, storage):
    renderer = SpyRenderer(db_session, clip)
    execute(clip, db_session, settings, storage, renderer)
    final = ClipArtifactStore(storage).final_path(clip.id)
    stamp = final.stat().st_mtime_ns

    execute(clip, db_session, settings, storage, renderer)

    assert len(renderer.calls) == 1
    assert final.stat().st_mtime_ns == stamp  # the artifact was not touched


def test_live_clip_is_not_rendered_twice(db_session, clip, settings, storage):
    clip.status = ClipStatus.RENDERING
    clip.heartbeat_at = datetime.now(UTC)
    db_session.commit()
    renderer = SpyRenderer(db_session, clip)
    result = execute(clip, db_session, settings, storage, renderer)
    assert result.status == ClipStatus.RENDERING and renderer.calls == []


def test_stale_clip_is_reclaimed_and_leftover_temp_removed(db_session, clip, settings, storage):
    clip.status = ClipStatus.RENDERING
    clip.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.clip_render_stale_after_seconds + 60
    )
    db_session.commit()
    ClipArtifactStore(storage).temp_path(clip.id).write_bytes(b"half")
    assert is_stale(clip, settings)

    result = execute(clip, db_session, settings, storage, SpyRenderer(db_session, clip))

    assert result.status == ClipStatus.READY
    assert ClipArtifactStore(storage).final_path(clip.id).read_bytes() == b"\x00" * 2048


def test_failed_clip_is_ignored_until_reset(db_session, clip, settings, storage):
    clip.status = ClipStatus.FAILED
    db_session.commit()
    renderer = SpyRenderer(db_session, clip)
    result = execute(clip, db_session, settings, storage, renderer)
    assert result.status == ClipStatus.FAILED and renderer.calls == []


def test_clip_owned_by_a_newer_task_is_ignored(db_session, clip, settings, storage):
    clip.celery_task_id = "task-2"
    db_session.commit()
    renderer = SpyRenderer(db_session, clip)
    result = execute(clip, db_session, settings, storage, renderer, task_id="task-1")
    assert result.status == ClipStatus.QUEUED and renderer.calls == []


def test_takeover_before_finalize_stops_without_writing(db_session, clip, settings, storage):
    def stolen(row, db, task_id):
        db.rollback()
        raise pipeline.PipelineSuperseded()

    original = pipeline._ensure_still_owner
    pipeline._ensure_still_owner = stolen
    try:
        result = execute(
            clip, db_session, settings, storage, SpyRenderer(db_session, clip), task_id="task-1"
        )
    finally:
        pipeline._ensure_still_owner = original
    db_session.refresh(result)
    assert result.status != ClipStatus.READY and result.storage_key is None


def test_unknown_clip_is_a_quiet_noop(db_session, settings, storage):
    assert run_clip_render(uuid.uuid4(), db_session, settings=settings, storage=storage) is None


def test_is_stale_semantics(settings):
    now = datetime.now(UTC)
    old = now - timedelta(seconds=settings.clip_render_stale_after_seconds + 1)
    assert not is_stale(
        Clip(status="rendering", heartbeat_at=now, created_at=now), settings, now=now
    )
    assert is_stale(Clip(status="rendering", heartbeat_at=old, created_at=now), settings, now=now)
    assert is_stale(Clip(status="validating", heartbeat_at=old, created_at=now), settings, now=now)
    for status in ("queued", "ready", "failed"):
        assert not is_stale(
            Clip(status=status, heartbeat_at=old, created_at=now), settings, now=now
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
    monkeypatch, db_session, clip, settings, storage
):
    assert "peaksift.render_clip" in celery_app.tasks
    monkeypatch.setattr("app.workers.clip_render_tasks.SessionLocal", lambda: _Reusable(db_session))
    monkeypatch.setattr(pipeline, "render_clip", SpyRenderer(db_session, clip))
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    clip.celery_task_id = None  # eager mode assigns its own id
    db_session.commit()

    render_clip_task.delay(str(clip.id))

    db_session.refresh(clip)
    assert clip.status == ClipStatus.READY


def test_task_with_invalid_id_is_a_noop():
    render_clip_task.delay("not-a-uuid")  # must not raise


def test_enqueue_uses_the_pre_chosen_task_id(monkeypatch):
    seen: dict = {}

    def fake_apply_async(*, args, task_id, retry):
        seen.update(args=args, task_id=task_id, retry=retry)

    monkeypatch.setattr(dispatch.render_clip_task, "apply_async", fake_apply_async)
    clip_id, task_id = uuid.uuid4(), new_task_id()
    assert enqueue_clip_render(clip_id, task_id=task_id) == task_id
    assert seen == {"args": [str(clip_id)], "task_id": task_id, "retry": False}


def test_enqueue_when_broker_is_down_is_a_controlled_error(monkeypatch):
    def failing(**kwargs):
        raise OperationalError("Error 61 connecting to localhost:6379. Connection refused.")

    monkeypatch.setattr(dispatch.render_clip_task, "apply_async", failing)
    with pytest.raises(JobQueueUnavailable):
        enqueue_clip_render(uuid.uuid4(), task_id=new_task_id())


# --- hardening -----


def _take_over(clip, db_session, *, new_task: str = "task-2", attempt: int = 2) -> None:
    """What the retry endpoint does to a stalled clip while the old worker is still alive."""
    clip.celery_task_id = new_task
    clip.attempt = attempt
    clip.status = ClipStatus.QUEUED
    db_session.commit()


def test_zombie_that_fails_after_takeover_leaves_the_new_attempt_alone(
    db_session, clip, settings, storage
):
    store = ClipArtifactStore(storage)

    def zombie(source, target, *, start, end, options, heartbeat=None):
        target.write_bytes(b"zombie partial")
        # Meanwhile a retry hands the row to task-2, whose render is already in progress.
        _take_over(clip, db_session)
        store.temp_path(clip.id, 2).write_bytes(b"attempt 2 output")
        raise RenderError("ffmpeg_failed", "Rendering failed (ffmpeg exit code 1)")

    result = execute(clip, db_session, settings, storage, zombie, task_id="task-1")

    db_session.refresh(result)
    assert result.status == ClipStatus.QUEUED  # not overwritten with the zombie's failure
    assert result.error_code is None and result.celery_task_id == "task-2"
    assert (
        store.storage.path_for(f"clips/{clip.id}/clip-tmp-2.mp4").read_bytes()
        == b"attempt 2 output"
    )
    assert not store.storage.path_for(f"clips/{clip.id}/clip-tmp-1.mp4").exists()


def test_zombie_stops_at_its_next_heartbeat_without_writing(db_session, clip, settings, storage):
    progress_seen: list[int] = []

    def zombie(source, target, *, start, end, options, heartbeat=None):
        heartbeat()  # still the owner: fine
        _take_over(clip, db_session)
        clip.progress_percent = 55  # would be committed by a naive heartbeat
        progress_seen.append(clip.progress_percent)
        heartbeat()  # must raise: the row belongs to task-2 now
        raise AssertionError("heartbeat should have stopped the zombie")

    result = execute(clip, db_session, settings, storage, zombie, task_id="task-1")

    db_session.expire_all()
    row = db_session.get(Clip, clip.id)
    assert row.status == ClipStatus.QUEUED and row.progress_percent != 55
    assert row.celery_task_id == "task-2" and row.error_code is None
    assert result is not None and progress_seen == [55]


def test_db_failure_after_finalize_leaves_no_ready_row_and_no_file(
    monkeypatch, db_session, clip, settings, storage
):
    """File renamed into place, then the commit that would mark it ready fails."""
    real_heartbeat = pipeline._heartbeat

    def failing_ready_commit(row, db, task_id=None):
        if row.status == ClipStatus.READY:
            raise RuntimeError("database went away")
        real_heartbeat(row, db, task_id)

    monkeypatch.setattr(pipeline, "_heartbeat", failing_ready_commit)
    result = execute(clip, db_session, settings, storage, SpyRenderer(db_session, clip))

    db_session.refresh(result)
    assert result.status == ClipStatus.FAILED and result.error_code == "internal_error"
    assert result.storage_key is None
    assert not ClipArtifactStore(storage).exists(clip.id)  # no orphaned "ready-looking" file


@requires_ffmpeg
def test_heartbeat_failure_kills_ffmpeg(tmp_path):
    """If the heartbeat raises (takeover, DB down), the ffmpeg child must not keep running."""
    import os
    import stat

    from app.services.clip_render.renderer import RenderOptions, render_clip

    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    pid_file = tmp_path / "pid"
    fake = tmp_path / "fake-ffmpeg"
    fake.write_text(f"#!/bin/sh\necho $$ > '{pid_file}'\nexec sleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    class Boom(Exception):
        pass

    def heartbeat():
        if pid_file.exists():  # only once the child is really running (macOS may scan it first)
            raise Boom()

    with pytest.raises(Boom):
        render_clip(
            source,
            tmp_path / "out.mp4",
            start=0,
            end=1,
            options=RenderOptions(
                ffmpeg_path=str(fake), timeout_seconds=30, heartbeat_interval_seconds=0.2
            ),
            heartbeat=heartbeat,
        )
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # the child is gone


@requires_ffmpeg
def test_logged_ffmpeg_errors_do_not_contain_media_paths(tmp_path, caplog):
    import logging
    import stat

    from app.services.clip_render.renderer import RenderOptions, render_clip

    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    target = tmp_path / "out" / "clip-tmp-1.mp4"
    fake = tmp_path / "fake-ffmpeg"
    fake.write_text(f"#!/bin/sh\necho 'cannot open {source} or {target}' >&2\nexit 3\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    with (
        caplog.at_level(logging.WARNING, logger="app.services.clip_render.renderer"),
        pytest.raises(RenderError),
    ):
        render_clip(source, target, start=0, end=1, options=RenderOptions(ffmpeg_path=str(fake)))
    assert "cannot open <source> or <output>" in caplog.text
    assert str(tmp_path) not in caplog.text
