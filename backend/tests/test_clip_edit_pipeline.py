import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kombu.exceptions import OperationalError
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    ClipEditStatus,
    Project,
    Transcription,
    TranscriptSegment,
    User,
    Video,
)
from app.services.clip_edit import pipeline
from app.services.clip_edit.composition import ComposedShort
from app.services.clip_edit.config import (
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    RENDER_PROFILE_VERTICAL_V1,
    EditConfig,
)
from app.services.clip_edit.pipeline import is_stale, run_clip_edit
from app.services.clip_edit.storage import (
    EditArtifactExists,
    EditArtifactMissing,
    EditArtifactStore,
    edit_storage_key,
    workspace_key,
)
from app.services.clip_render.renderer import RenderError
from app.services.clip_render.storage import clip_storage_key
from app.services.storage import InvalidStorageKey, LocalStorageProvider
from app.workers import dispatch
from app.workers.celery_app import celery_app
from app.workers.clip_edit_tasks import render_clip_edit_task
from app.workers.dispatch import JobQueueUnavailable, enqueue_clip_edit, new_task_id
from tests.media_fixtures import generate_video, have_ffmpeg, requires_ffmpeg, requires_libass

CLIP_START, CLIP_END = 2.0, 5.0  # the clip covers 2–5 s of the source


@pytest.fixture
def settings() -> Settings:
    return Settings(**{**get_settings().model_dump(), "clip_render_preset": "ultrafast"})


@pytest.fixture
def storage() -> LocalStorageProvider:
    return LocalStorageProvider(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalStorageProvider):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


def make_edit(
    db_session: Session,
    storage: LocalStorageProvider,
    *,
    captions=True,
    layout="blur_background",
    segments=None,
) -> ClipEdit:
    user = User(email=f"c-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="s.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=1,
        status="ready",
        duration_seconds=10.0,
    )
    transcription = Transcription(
        video=video, provider="fake", model="f", status="completed", language="en"
    )
    for i, (start, end, text) in enumerate(
        segments
        if segments is not None
        else [(1.0, 3.5, "Hello there friends"), (3.5, 6.0, "this is the payoff")]
    ):
        transcription.segments.append(
            TranscriptSegment(sequence_index=i, start_time=start, end_time=end, text=text)
        )
    run = ClipDetectionRun(
        video=video,
        transcription=transcription,
        transcript_fingerprint="f" * 64,
        provider="o",
        model="m",
        config={},
        status="completed",
    )
    db_session.add_all([user, video, transcription, run])
    db_session.flush()
    candidate = ClipCandidate(
        run=run,
        video_id=video.id,
        start_time=CLIP_START,
        end_time=CLIP_END,
        duration_seconds=CLIP_END - CLIP_START,
        title="Moment",
        hook="h",
        rationale="r",
        category="story",
        transcript_excerpt="x",
        overall_score=80,
        hook_score=80,
        entertainment_score=80,
        clarity_score=80,
        payoff_score=80,
        completeness_score=80,
        rank=1,
    )
    clip = Clip(
        candidate=candidate,
        video_id=video.id,
        start_time=CLIP_START,
        end_time=CLIP_END,
        duration_seconds=CLIP_END - CLIP_START,
        status="ready",
    )
    db_session.add_all([candidate, clip])
    db_session.flush()
    clip.storage_key = clip_storage_key(clip.id)
    clip_path = storage.path_for(clip.storage_key)
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    if have_ffmpeg():
        generate_video(clip_path, seconds=CLIP_END - CLIP_START)
    else:
        clip_path.write_bytes(b"fake clip")
    config = EditConfig.create(layout=layout, captions_enabled=captions)
    edit = ClipEdit(
        clip=clip,
        video_id=video.id,
        config=config.snapshot(),
        config_fingerprint=config.fingerprint(),
        aspect_ratio=config.aspect_ratio.value,
        layout=config.layout.value,
        captions_enabled=config.captions_enabled,
        caption_style=config.caption_style.value if config.caption_style else None,
        caption_position=config.caption_position.value if config.caption_position else None,
        caption_renderer=config.caption_renderer,
        output_width=OUTPUT_WIDTH,
        output_height=OUTPUT_HEIGHT,
        render_profile=RENDER_PROFILE_VERTICAL_V1,
        celery_task_id="task-1",
    )
    db_session.add(edit)
    db_session.commit()
    return edit


def fake_composed(target: Path) -> ComposedShort:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x00" * 4096)
    return ComposedShort(
        path=target,
        size_bytes=4096,
        duration_seconds=3.0,
        width=1080,
        height=1920,
        fps=25.0,
        video_codec="h264",
        audio_codec="aac",
    )


class SpyComposer:
    def __init__(
        self, db: Session, edit: ClipEdit, *, error: Exception | None = None, on_call=None
    ):
        self.db, self.edit, self.error, self.on_call = db, edit, error, on_call
        self.calls: list[dict] = []

    def __call__(
        self,
        source,
        target,
        *,
        layout,
        options,
        workspace,
        captions,
        caption_font,
        heartbeat,
        crop_points=None,
        focus=None,
    ):
        self.calls.append(
            {
                "source": source,
                "target": target,
                "layout": layout,
                "workspace": workspace,
                "captions": captions,
                "caption_font": caption_font,
                "crop_points": crop_points,
                "focus": focus,
            }
        )
        self.captions_text = (workspace / "captions.ass").read_text() if captions else None
        heartbeat()
        if self.on_call:
            self.on_call()
            heartbeat()
        if self.error:
            raise self.error
        return fake_composed(target)


def execute(edit, db, settings, storage, composer, task_id="task-1"):
    return run_clip_edit(
        edit.id, db, settings=settings, storage=storage, composer=composer, task_id=task_id
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- storage -----


def test_storage_keys_are_generated_and_attempt_scoped():
    edit_id = uuid.uuid4()
    assert edit_storage_key(edit_id) == f"edits/{edit_id}/edited.mp4"
    assert workspace_key(edit_id, 2) == f"edits/{edit_id}/work-2"
    for bad in ("../x", "title", ""):
        with pytest.raises(ValueError):
            edit_storage_key(bad)
    for attempt in (0, -1, True, "2"):
        with pytest.raises(ValueError):
            workspace_key(edit_id, attempt)


def test_workspaces_are_isolated_and_finalize_is_atomic(tmp_path: Path):
    store = EditArtifactStore(
        LocalStorageProvider(tmp_path / "media"), LocalStorageProvider(tmp_path / "work")
    )
    edit_id = uuid.uuid4()
    store.workspace(edit_id, 1)
    store.workspace(edit_id, 2)
    store.render_path(edit_id, 1).write_bytes(b"zombie")
    store.render_path(edit_id, 2).write_bytes(b"fresh")
    store.discard_workspace(edit_id, 1)
    assert store.render_path(edit_id, 2).read_bytes() == b"fresh"
    with pytest.raises(EditArtifactMissing):
        store.finalize(edit_id, 1)
    assert store.finalize(edit_id, 2) == edit_storage_key(edit_id)
    assert (
        store.storage.path_for(edit_storage_key(edit_id)).read_bytes() == b"fresh"
        and not store.render_path(edit_id, 2).exists()
    )
    store.workspace(edit_id, 3)
    store.render_path(edit_id, 3).write_bytes(b"again")
    with pytest.raises(EditArtifactExists):
        store.finalize(edit_id, 3)  # never overwrite a final artifact
    store.discard(edit_id)
    assert not store.storage.path_for(f"edits/{edit_id}").exists()
    assert not store.scratch.path_for(f"edits/{edit_id}").exists()


def test_workspace_creation_clears_crash_leftovers(tmp_path: Path):
    store = EditArtifactStore(LocalStorageProvider(tmp_path / "media"))
    edit_id = uuid.uuid4()
    store.workspace(edit_id, 1)
    store.captions_path(edit_id, 1).write_text("stale")
    store.render_path(edit_id, 1).write_bytes(b"half")
    fresh = store.workspace(edit_id, 1)  # a redelivered attempt starts from an empty directory
    assert fresh.is_dir() and list(fresh.iterdir()) == []


def test_symlinked_edit_directory_cannot_escape(tmp_path: Path):
    store = EditArtifactStore(
        LocalStorageProvider(tmp_path / "media"), LocalStorageProvider(tmp_path / "work")
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    edit_id = uuid.uuid4()
    for root in (store.storage.root, store.scratch.root):
        (root / "edits").mkdir(parents=True)
        (root / "edits" / str(edit_id)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(InvalidStorageKey):
        store.exists(edit_id)
    with pytest.raises(InvalidStorageKey):
        store.workspace(edit_id, 1)


# --- real renders -----


@requires_ffmpeg
@requires_libass
def test_real_captioned_render_becomes_ready_and_leaves_the_clip_untouched(
    db_session, settings, storage
):
    edit = make_edit(db_session, storage, captions=True)
    clip_file = storage.path_for(edit.clip.storage_key)
    before = digest(clip_file)

    result = run_clip_edit(
        edit.id, db_session, settings=settings, storage=storage, task_id="task-1"
    )

    assert result.status == ClipEditStatus.READY and result.progress_percent == 100, (
        result.error_message
    )
    assert result.storage_key == edit_storage_key(edit.id)
    assert (result.width, result.height) == (1080, 1920) and result.video_codec == "h264"
    assert result.audio_codec == "aac" and abs(result.duration_seconds - 3.0) <= 0.5
    assert result.caption_cue_count and result.caption_cue_count >= 1
    edit_dir = storage.path_for(f"edits/{edit.id}")
    assert sorted(p.name for p in edit_dir.iterdir()) == ["edited.mp4"]  # no captions.ass, no temp
    assert digest(clip_file) == before  # the V0.5 clip is never modified


@requires_ffmpeg
def test_real_render_without_captions(db_session, settings, storage):
    edit = make_edit(db_session, storage, captions=False, layout="center_crop")
    result = run_clip_edit(
        edit.id, db_session, settings=settings, storage=storage, task_id="task-1"
    )
    assert result.status == ClipEditStatus.READY, result.error_message
    assert result.caption_cue_count is None and (result.width, result.height) == (1080, 1920)


# --- captions preparation (fake composer) -----


def test_caption_file_comes_from_the_transcript_in_clip_local_time(db_session, settings, storage):
    edit = make_edit(
        db_session,
        storage,
        segments=[
            (1.0, 3.5, "Hello there friends"),
            (3.5, 6.0, "this is the payoff"),
            (8.0, 9.0, "after the clip"),
        ],
    )
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)

    (call,) = composer.calls
    assert call["captions"] is True and call["layout"].value == "blur_background"
    text = composer.captions_text
    assert "PlayResX: 1080" in text and "Style: Caption,Noto Sans,80," in text  # bold preset
    dialogues = [line.split(",", 9) for line in text.splitlines() if line.startswith("Dialogue:")]
    assert dialogues and edit.caption_cue_count == len(dialogues)

    def seconds(stamp: str) -> float:
        h, m, s = stamp.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    for fields in dialogues:
        assert 0.0 <= seconds(fields[1]) < seconds(fields[2]) <= 3.0  # clip-local, inside 3 s
    spoken = " ".join(fields[9] for fields in dialogues).split()
    transcript_words = "Hello there friends this is the payoff".split()
    assert spoken and all(word in transcript_words for word in spoken)  # only transcript words
    assert spoken == [w for w in transcript_words if w in spoken]  # in transcript order
    assert "after" not in spoken  # the segment outside the clip is excluded


def test_no_speech_in_range_renders_without_a_caption_layer(db_session, settings, storage):
    edit = make_edit(db_session, storage, segments=[(7.0, 9.0, "only later")])
    composer = SpyComposer(db_session, edit)
    result = execute(edit, db_session, settings, storage, composer)
    assert result.status == ClipEditStatus.READY and result.caption_cue_count == 0
    assert composer.calls[0]["captions"] is False


def test_captions_need_a_completed_transcript(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    edit.clip.video.transcription.status = "transcribing"
    db_session.commit()
    composer = SpyComposer(db_session, edit)
    result = execute(edit, db_session, settings, storage, composer)
    assert result.status == ClipEditStatus.FAILED and result.error_code == "transcript_unavailable"
    assert composer.calls == [] and not storage.path_for(f"edits/{edit.id}").exists()


def test_stored_snapshot_drives_the_render(db_session, settings, storage):
    edit = make_edit(db_session, storage, captions=False, layout="fit")
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)
    assert composer.calls[0]["layout"].value == "fit" and composer.calls[0]["captions"] is False


# --- failures -----


@pytest.mark.parametrize("problem", ["not_ready", "missing_file", "bad_key"])
def test_unusable_source_clip_fails_safely(db_session, settings, storage, problem):
    edit = make_edit(db_session, storage)
    if problem == "not_ready":
        edit.clip.status = "failed"
    elif problem == "missing_file":
        storage.path_for(edit.clip.storage_key).unlink()
    else:
        edit.clip.storage_key = "../../etc/passwd"
    db_session.commit()
    result = execute(edit, db_session, settings, storage, SpyComposer(db_session, edit))
    assert result.status == ClipEditStatus.FAILED
    assert (
        result.error_code in {"clip_not_ready", "clip_missing"} and "/" not in result.error_message
    )


def test_render_error_is_recorded_and_all_artifacts_removed(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    composer = SpyComposer(
        db_session,
        edit,
        error=RenderError("render_timeout", "Rendering timed out after 1800 seconds"),
    )
    result = execute(edit, db_session, settings, storage, composer)
    assert result.status == ClipEditStatus.FAILED and result.error_code == "render_timeout"
    assert result.storage_key is None and not storage.path_for(f"edits/{edit.id}").exists()


def test_unexpected_exception_is_generic_and_path_free(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    composer = SpyComposer(db_session, edit, error=RuntimeError(f"boom at {storage.root}"))
    result = execute(edit, db_session, settings, storage, composer)
    assert result.error_code == "internal_error" and str(storage.root) not in result.error_message


def test_db_failure_after_finalize_leaves_no_ready_row_and_no_file(
    monkeypatch, db_session, settings, storage
):
    edit = make_edit(db_session, storage)
    real = pipeline._heartbeat

    def failing_ready_commit(row, db, task_id=None):
        if row.status == ClipEditStatus.READY:
            raise RuntimeError("database went away")
        real(row, db, task_id)

    monkeypatch.setattr(pipeline, "_heartbeat", failing_ready_commit)
    result = execute(edit, db_session, settings, storage, SpyComposer(db_session, edit))
    db_session.refresh(result)
    assert result.status == ClipEditStatus.FAILED and result.storage_key is None
    assert not EditArtifactStore(storage).exists(edit.id)


# --- progress, idempotency, ownership -----


def test_stages_and_progress_are_honest_and_monotonic(monkeypatch, db_session, settings, storage):
    edit = make_edit(db_session, storage)
    seen = []
    real = pipeline._heartbeat

    def spy(row, db, task_id=None):
        real(row, db, task_id)
        seen.append((row.status, row.progress_percent))

    monkeypatch.setattr(pipeline, "_heartbeat", spy)
    execute(edit, db_session, settings, storage, SpyComposer(db_session, edit))
    progress = [p for _, p in seen]
    assert progress == sorted(progress) and progress[-1] == 100
    assert ("rendering", 15) in seen and ("validating", 90) in seen and ("ready", 100) in seen


def test_ready_edit_ignores_duplicate_delivery(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)
    stamp = storage.path_for(edit_storage_key(edit.id)).stat().st_mtime_ns
    execute(edit, db_session, settings, storage, composer)
    assert (
        len(composer.calls) == 1
        and storage.path_for(edit_storage_key(edit.id)).stat().st_mtime_ns == stamp
    )


def test_live_edit_is_not_rendered_twice_and_stale_is_reclaimed(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    edit.status, edit.heartbeat_at = ClipEditStatus.RENDERING, datetime.now(UTC)
    db_session.commit()
    composer = SpyComposer(db_session, edit)
    assert execute(edit, db_session, settings, storage, composer).status == ClipEditStatus.RENDERING
    assert composer.calls == []

    edit.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.clip_render_stale_after_seconds + 60
    )
    db_session.commit()
    assert is_stale(edit, settings)
    assert execute(edit, db_session, settings, storage, composer).status == ClipEditStatus.READY


def test_failed_edit_and_newer_task_are_ignored(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    edit.status = ClipEditStatus.FAILED
    db_session.commit()
    composer = SpyComposer(db_session, edit)
    assert execute(edit, db_session, settings, storage, composer).status == ClipEditStatus.FAILED
    edit.status, edit.celery_task_id = ClipEditStatus.QUEUED, "task-2"
    db_session.commit()
    assert (
        execute(edit, db_session, settings, storage, composer, task_id="task-1").status
        == ClipEditStatus.QUEUED
    )
    assert composer.calls == []


def _take_over(db_session, edit):
    db_session.execute(
        update(ClipEdit)
        .where(ClipEdit.id == edit.id)
        .values(celery_task_id="task-2", attempt=2, status="rendering", progress_percent=15)
    )
    db_session.commit()
    store = EditArtifactStore(LocalStorageProvider(Path(get_settings().media_root)))
    store.workspace(edit.id, 2)
    store.render_path(edit.id, 2).write_bytes(b"attempt 2 output")


def test_stalled_attempt_cannot_touch_the_new_attempt(db_session, settings, storage):
    """attempt 1 starts → stalls → retry starts attempt 2 → attempt 1 resumes and fails."""
    edit = make_edit(db_session, storage)
    composer = SpyComposer(db_session, edit, on_call=lambda: _take_over(db_session, edit))
    execute(edit, db_session, settings, storage, composer)

    db_session.expire_all()
    row = db_session.get(ClipEdit, edit.id)
    assert (
        row.celery_task_id == "task-2" and row.status == "rendering" and row.progress_percent == 15
    )
    assert row.error_code is None and row.storage_key is None
    store = EditArtifactStore(storage)
    assert store.render_path(edit.id, 2).read_bytes() == b"attempt 2 output"
    assert not store.scratch.path_for(workspace_key(edit.id, 1)).exists()  # its own files only


def test_stalled_attempt_cannot_complete_the_new_attempt(db_session, settings, storage):
    edit = make_edit(db_session, storage)

    def takes_over_after_render(source, target, **kwargs):
        result = fake_composed(target)
        _take_over(db_session, edit)
        return result

    execute(edit, db_session, settings, storage, takes_over_after_render)
    db_session.expire_all()
    row = db_session.get(ClipEdit, edit.id)
    assert row.status == "rendering" and row.completed_at is None
    assert not EditArtifactStore(storage).exists(edit.id)


def test_edit_deleted_mid_render_stops_quietly_and_leaves_no_files(db_session, settings, storage):
    """The project/video/clip (and so the edit) is removed while the worker renders."""
    edit = make_edit(db_session, storage)
    edit_id = edit.id

    def delete_row():
        db_session.execute(delete(ClipEdit).where(ClipEdit.id == edit_id))
        db_session.commit()

    execute(edit, db_session, settings, storage, SpyComposer(db_session, edit, on_call=delete_row))
    db_session.expire_all()
    assert db_session.get(ClipEdit, edit_id) is None
    assert not storage.path_for(f"edits/{edit_id}").exists()


def test_disk_errors_are_reported_as_storage_failures(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    disk_full = OSError(28, "No space left on device", str(storage.root / "edits"))
    result = execute(
        edit, db_session, settings, storage, SpyComposer(db_session, edit, error=disk_full)
    )
    assert result.status == ClipEditStatus.FAILED and result.error_code == "storage_failure"
    assert str(storage.root) not in result.error_message
    assert not storage.path_for(f"edits/{edit.id}").exists()


def test_a_failing_database_while_recording_a_failure_does_not_raise(
    monkeypatch, db_session, settings, storage
):
    edit = make_edit(db_session, storage)

    def database_down(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(pipeline, "_fail", database_down)
    composer = SpyComposer(db_session, edit, error=RenderError("ffmpeg_failed", "Rendering failed"))
    execute(edit, db_session, settings, storage, composer)  # must not raise into Celery
    db_session.expire_all()
    row = db_session.get(ClipEdit, edit.id)
    assert row.status == ClipEditStatus.RENDERING  # left for stale recovery + retry
    assert not EditArtifactStore(storage).scratch.path_for(workspace_key(edit.id, 1)).exists()


def test_the_configured_caption_font_reaches_the_renderer(db_session, settings, storage):
    edit = make_edit(db_session, storage)
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)
    assert composer.calls[0]["caption_font"] == settings.caption_font_family


def test_unknown_edit_is_a_quiet_noop(db_session, settings, storage):
    assert run_clip_edit(uuid.uuid4(), db_session, settings=settings, storage=storage) is None


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
    assert "peaksift.render_clip_edit" in celery_app.tasks
    edit = make_edit(db_session, storage)
    monkeypatch.setattr("app.workers.clip_edit_tasks.SessionLocal", lambda: _Reusable(db_session))
    monkeypatch.setattr(pipeline, "compose_short", SpyComposer(db_session, edit))
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    edit.celery_task_id = None
    db_session.commit()
    render_clip_edit_task.delay(str(edit.id))
    db_session.refresh(edit)
    assert edit.status == ClipEditStatus.READY


def test_task_with_invalid_id_is_a_noop():
    render_clip_edit_task.delay("not-a-uuid")


def test_enqueue_uses_the_pre_chosen_task_id(monkeypatch):
    seen = {}

    def fake_apply_async(*, args, task_id, retry):
        seen.update(args=args, task_id=task_id, retry=retry)

    monkeypatch.setattr(dispatch.render_clip_edit_task, "apply_async", fake_apply_async)
    edit_id, task_id = uuid.uuid4(), new_task_id()
    assert enqueue_clip_edit(edit_id, task_id=task_id) == task_id
    assert seen == {"args": [str(edit_id)], "task_id": task_id, "retry": False}


def test_enqueue_when_broker_is_down(monkeypatch):
    def failing(**kwargs):
        raise OperationalError("connection refused")

    monkeypatch.setattr(dispatch.render_clip_edit_task, "apply_async", failing)
    with pytest.raises(JobQueueUnavailable):
        enqueue_clip_edit(uuid.uuid4(), task_id=new_task_id())
