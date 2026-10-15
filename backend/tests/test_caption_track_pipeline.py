"""The caption-timing job with a scripted provider (no model, no FFmpeg needed)."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kombu.exceptions import OperationalError
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import CaptionTrack, CaptionTrackStatus, CaptionWord
from app.services.caption_timing import pipeline
from app.services.caption_timing.contract import (
    CaptionTimingError,
    CaptionTimingResult,
    TimedWord,
    TimingCapabilities,
    TimingOutputError,
    TimingUnavailable,
)
from app.services.caption_timing.pipeline import clip_local_words, is_stale, run_caption_track
from app.services.clip_render.storage import clip_storage_key
from app.services.storage import LocalStorageProvider
from app.workers import dispatch
from app.workers.celery_app import celery_app
from app.workers.dispatch import JobQueueUnavailable, enqueue_caption_track, new_task_id
from tests.test_caption_track_model import make_track
from tests.test_clip_edit_model import make_clip

WORDS = (
    TimedWord(0.10, 0.40, "Nobody", 0.95),
    TimedWord(0.45, 0.80, "tells", 0.9),
    TimedWord(0.85, 1.10, "you", 0.85),
    TimedWord(1.30, 1.90, "anything.", 0.8),
)


class ScriptedTiming:
    """A word-timing provider double: returns fixed words; can fail or run a hook."""

    name, model = "faster_whisper", "test-double"

    def __init__(
        self, words=WORDS, *, error=None, on_call=None, word_timestamps=True, duration=20.0
    ):
        self.words, self.error, self.on_call, self.duration = words, error, on_call, duration
        self.capabilities = TimingCapabilities(word_timestamps, True, True)
        self.calls: list = []

    def time_words(self, request):
        self.calls.append(request)
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        return CaptionTimingResult(
            self.name, self.model, "en", 0.97, self.duration, tuple(self.words), 1
        )


@pytest.fixture
def settings() -> Settings:
    return Settings(**get_settings().model_dump())


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


def ready_track(
    db: Session, storage: LocalStorageProvider, *, with_file=True, audio=True
) -> CaptionTrack:
    clip = make_clip(db)
    clip.storage_key = clip_storage_key(clip.id)
    clip.audio_codec = "aac" if audio else None
    db.commit()
    if with_file:
        path = storage.path_for(clip.storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"clip bytes (the scripted provider never decodes them)")
    return make_track(db, clip)


def run(track, db, settings, storage, provider, task_id="task-1"):
    return run_caption_track(
        track.id, db, settings=settings, storage=storage, provider=provider, task_id=task_id
    )


def words(db, track_id):
    return db.scalars(
        select(CaptionWord)
        .where(CaptionWord.caption_track_id == track_id)
        .order_by(CaptionWord.sequence_index)
    ).all()


# --- success -----


def test_successful_alignment_persists_ordered_clip_local_words(db_session, settings, storage):
    track = ready_track(db_session, storage)
    provider = ScriptedTiming()
    result = run(track, db_session, settings, storage, provider)
    assert result.status == CaptionTrackStatus.COMPLETED and result.progress_percent == 100
    stored = words(db_session, track.id)
    assert [(w.sequence_index, w.start_time, w.end_time, w.text) for w in stored] == [
        (0, 0.10, 0.40, "Nobody"),
        (1, 0.45, 0.80, "tells"),
        (2, 0.85, 1.10, "you"),
        (3, 1.30, 1.90, "anything."),
    ]
    assert result.word_count == 4 and result.rejected_word_count == 1  # as the provider reported
    assert result.language == "en" and result.language_probability == 0.97
    assert (
        result.average_confidence == pytest.approx(0.875) and result.audio_duration_seconds == 20.0
    )
    # The provider was given the clip's own file and the snapshot's language hint.
    request = provider.calls[0]
    assert (
        request.audio_path == storage.path_for(track.clip.storage_key)
        and request.language_hint == "en"
    )
    assert result.error_code is None and result.completed_at is not None


def test_progress_is_honest_and_monotonic(monkeypatch, db_session, settings, storage):
    track = ready_track(db_session, storage)
    seen = []
    real = pipeline._heartbeat

    def spy(row, db, task_id=None):
        real(row, db, task_id)
        seen.append((row.status, row.progress_percent))

    monkeypatch.setattr(pipeline, "_heartbeat", spy)
    run(track, db_session, settings, storage, ScriptedTiming())
    assert seen == [
        ("preparing_audio", 10),
        ("aligning", 20),
        ("validating", 85),
        ("completed", 100),
    ]


def test_silence_gives_a_completed_track_with_no_words(db_session, settings, storage):
    result = run(
        ready_track(db_session, storage), db_session, settings, storage, ScriptedTiming(words=())
    )
    assert result.status == CaptionTrackStatus.COMPLETED and result.word_count == 0
    assert result.average_confidence is None and words(db_session, result.id) == []


def test_a_clip_without_audio_completes_with_zero_words_without_calling_the_provider(
    db_session, settings, storage
):
    provider = ScriptedTiming()
    result = run(
        ready_track(db_session, storage, audio=False), db_session, settings, storage, provider
    )
    assert result.status == CaptionTrackStatus.COMPLETED and result.word_count == 0
    assert provider.calls == []


def test_words_past_the_end_of_the_clip_are_dropped_or_clamped():
    kept, rejected = clip_local_words(
        (
            TimedWord(1.0, 1.4, "inside"),
            TimedWord(19.8, 20.2, "edge"),
            TimedWord(20.1, 20.4, "after"),
        ),
        20.0,
    )
    assert [(w.text, w.end) for w in kept] == [("inside", 1.4), ("edge", 20.0)] and rejected == 1


# --- failures -----


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            TimingUnavailable("model_load_failed", "The speech model could not be loaded"),
            "model_load_failed",
        ),
        (
            CaptionTimingError("provider_failure", "Word timing failed (RuntimeError)"),
            "provider_failure",
        ),
        (TimingOutputError("Word 3 is out of order (1.000s)"), "timing_output_invalid"),
    ],
)
def test_provider_failures_are_recorded_safely_with_no_words(
    db_session, settings, storage, error, code
):
    result = run(
        ready_track(db_session, storage), db_session, settings, storage, ScriptedTiming(error=error)
    )
    assert result.status == CaptionTrackStatus.FAILED and result.error_code == code
    assert words(db_session, result.id) == [] and result.word_count is None


def test_a_provider_without_word_timestamps_is_refused(db_session, settings, storage):
    provider = ScriptedTiming(word_timestamps=False)
    result = run(ready_track(db_session, storage), db_session, settings, storage, provider)
    assert result.status == CaptionTrackStatus.FAILED and result.error_code == "provider_capability"
    assert provider.calls == []


@pytest.mark.parametrize(
    ("with_file", "ready", "code"), [(False, True, "clip_missing"), (True, False, "clip_not_ready")]
)
def test_clip_problems_are_reported(db_session, settings, storage, with_file, ready, code):
    track = ready_track(db_session, storage, with_file=with_file)
    if not ready:
        track.clip.status = "rendering"
        db_session.commit()
    result = run(track, db_session, settings, storage, ScriptedTiming())
    assert result.status == CaptionTrackStatus.FAILED and result.error_code == code
    assert str(storage.root) not in result.error_message


def test_unexpected_errors_are_generic_and_path_free(db_session, settings, storage):
    error = RuntimeError(f"boom at {storage.root}/clips/secret.mp4")
    result = run(
        ready_track(db_session, storage), db_session, settings, storage, ScriptedTiming(error=error)
    )
    assert result.error_code == "internal_error" and str(storage.root) not in result.error_message


def test_transaction_failure_at_finalize_never_exposes_completed_words(
    monkeypatch, db_session, settings, storage
):
    track = ready_track(db_session, storage)
    real = pipeline._finalize

    def explode(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("database went away during commit")

    monkeypatch.setattr(pipeline, "_finalize", explode)
    result = run(track, db_session, settings, storage, ScriptedTiming())
    db_session.expire_all()
    row = db_session.get(CaptionTrack, result.id)
    assert row.status == CaptionTrackStatus.FAILED and words(db_session, row.id) == []


def test_an_unsupported_snapshot_fails_clearly(db_session, settings, storage):
    track = ready_track(db_session, storage)
    track.config = {"alignment_version": "caption_alignment_v0"}
    db_session.commit()
    result = run(track, db_session, settings, storage, ScriptedTiming())
    assert result.status == CaptionTrackStatus.FAILED and result.error_code == "config_invalid"


# --- idempotency and ownership -----


def test_completed_track_ignores_duplicate_delivery(db_session, settings, storage):
    track = ready_track(db_session, storage)
    run(track, db_session, settings, storage, ScriptedTiming())
    before = [(w.id, w.start_time) for w in words(db_session, track.id)]
    again = ScriptedTiming()
    run(track, db_session, settings, storage, again)
    assert (
        again.calls == [] and [(w.id, w.start_time) for w in words(db_session, track.id)] == before
    )


def test_failed_track_needs_an_explicit_retry(db_session, settings, storage):
    track = ready_track(db_session, storage)
    run(
        track,
        db_session,
        settings,
        storage,
        ScriptedTiming(error=CaptionTimingError("provider_failure", "x")),
    )
    again = ScriptedTiming()
    assert (
        run(track, db_session, settings, storage, again).status == CaptionTrackStatus.FAILED
        and again.calls == []
    )
    # what the retry endpoint does: new attempt, new token, queued
    track.status, track.attempt, track.celery_task_id = CaptionTrackStatus.QUEUED, 2, "task-2"
    db_session.commit()
    result = run(track, db_session, settings, storage, again, task_id="task-2")
    assert result.status == CaptionTrackStatus.COMPLETED and len(words(db_session, track.id)) == 4


def test_live_track_is_not_run_twice_but_a_stale_one_is_reclaimed(db_session, settings, storage):
    track = ready_track(db_session, storage)
    track.status, track.heartbeat_at = CaptionTrackStatus.ALIGNING, datetime.now(UTC)
    db_session.commit()
    busy = ScriptedTiming()
    run(track, db_session, settings, storage, busy)
    assert busy.calls == [] and not is_stale(track, settings)
    track.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.caption_timing_stale_after_seconds + 5
    )
    db_session.commit()
    assert is_stale(track, settings)
    assert (
        run(track, db_session, settings, storage, ScriptedTiming()).status
        == CaptionTrackStatus.COMPLETED
    )


def _take_over(db, track_id):
    db.execute(
        update(CaptionTrack)
        .where(CaptionTrack.id == track_id)
        .values(
            celery_task_id="task-2", attempt=2, status=CaptionTrackStatus.QUEUED, progress_percent=0
        )
    )
    db.commit()


def test_stalled_worker_cannot_write_after_a_retry_took_over(db_session, settings, storage):
    track = ready_track(db_session, storage)
    track_id = track.id
    run(
        track,
        db_session,
        settings,
        storage,
        ScriptedTiming(on_call=lambda: _take_over(db_session, track_id)),
    )
    db_session.expire_all()
    row = db_session.get(CaptionTrack, track_id)
    assert row.celery_task_id == "task-2" and row.status == CaptionTrackStatus.QUEUED
    assert (
        row.progress_percent == 0 and row.error_code is None and words(db_session, track_id) == []
    )


def test_old_worker_failing_after_a_takeover_cannot_mark_the_new_attempt_failed(
    db_session, settings, storage
):
    track = ready_track(db_session, storage)
    track_id = track.id

    def take_over_then_crash():
        _take_over(db_session, track_id)

    provider = ScriptedTiming(
        on_call=take_over_then_crash, error=CaptionTimingError("provider_failure", "x")
    )
    run(track, db_session, settings, storage, provider)
    db_session.expire_all()
    row = db_session.get(CaptionTrack, track_id)
    assert row.status == CaptionTrackStatus.QUEUED and row.error_code is None


def test_resumed_old_worker_cannot_touch_the_new_attempts_words(db_session, settings, storage):
    track = ready_track(db_session, storage)
    _take_over(db_session, track.id)
    run(
        track, db_session, settings, storage, ScriptedTiming(), task_id="task-2"
    )  # attempt 2 completes
    db_session.expire_all()
    done = [(w.id, w.text) for w in words(db_session, track.id)]
    old = ScriptedTiming(words=(TimedWord(0.0, 0.5, "stale"),))
    run(track, db_session, settings, storage, old, task_id="task-1")  # the old worker wakes up
    db_session.expire_all()
    assert (
        old.calls == []
        and db_session.get(CaptionTrack, track.id).status == CaptionTrackStatus.COMPLETED
    )
    assert [(w.id, w.text) for w in words(db_session, track.id)] == done


def test_track_deleted_mid_run_stops_quietly(db_session, settings, storage):
    track = ready_track(db_session, storage)
    track_id = track.id

    def delete_row():
        db_session.execute(delete(CaptionTrack).where(CaptionTrack.id == track_id))
        db_session.commit()

    run(track, db_session, settings, storage, ScriptedTiming(on_call=delete_row))
    db_session.expire_all()
    assert db_session.get(CaptionTrack, track_id) is None


def test_unknown_track_is_a_quiet_noop(db_session, settings, storage):
    assert run_caption_track(uuid.uuid4(), db_session, settings=settings, storage=storage) is None


def test_the_provider_is_built_from_the_snapshot_not_todays_settings(
    monkeypatch, db_session, settings, storage
):
    track = ready_track(db_session, storage)
    built = []

    def fake_factory(pinned):
        built.append((pinned.faster_whisper_model, pinned.faster_whisper_beam_size))
        return ScriptedTiming()

    monkeypatch.setattr(pipeline, "get_timing_provider", fake_factory)
    later = Settings(
        **{
            **settings.model_dump(),
            "faster_whisper_model": "large-v3",
            "faster_whisper_beam_size": 9,
        }
    )
    run_caption_track(track.id, db_session, settings=later, storage=storage, task_id="task-1")
    snapshot = track.config
    assert built == [(snapshot["model"], snapshot["beam_size"])]


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
    assert "peaksift.generate_caption_track" in celery_app.tasks
    track = ready_track(db_session, storage)
    token = new_task_id()
    track.celery_task_id = token
    db_session.commit()
    monkeypatch.setattr("app.workers.caption_tasks.SessionLocal", lambda: _Reusable(db_session))
    monkeypatch.setattr(pipeline, "get_timing_provider", lambda s: ScriptedTiming())
    enqueue_caption_track(track.id, task_id=token)
    db_session.expire_all()
    assert db_session.get(CaptionTrack, track.id).status == CaptionTrackStatus.COMPLETED


def test_task_with_invalid_id_is_a_noop():
    celery_app.tasks["peaksift.generate_caption_track"].apply(args=["not-a-uuid"]).get()


def test_enqueue_when_broker_is_down(monkeypatch):
    def down(*args, **kwargs):
        raise OperationalError("redis down")

    monkeypatch.setattr(dispatch.generate_caption_track_task, "apply_async", down)
    with pytest.raises(JobQueueUnavailable):
        enqueue_caption_track(uuid.uuid4(), task_id="t")
