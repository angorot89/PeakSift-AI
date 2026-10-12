import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Project, Transcription, TranscriptSegment, User, Video
from app.services.audio_extraction import AudioExtractionError, ExtractedAudio
from app.services.storage import LocalMediaStorage
from app.services.transcription import pipeline
from app.services.transcription.chunking import AudioChunk, ChunkingError
from app.services.transcription.contract import ProviderSegment, TranscriptionProviderError
from app.services.transcription.pipeline import is_stale, run_transcription
from app.workers.transcription_tasks import transcribe_video
from tests.fakes import FakeProvider
from tests.media_fixtures import generate_video, requires_ffmpeg

CHUNK_SECONDS = 600


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
def transcription(db_session: Session, storage: LocalMediaStorage) -> Transcription:
    user = User(email="creator@example.com", password_hash="x")
    project = Project(name="Stream", owner=user)
    key = storage.generate_key("mp4")
    storage.save(io.BytesIO(b"fake video"), key)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=key,
        content_type="video/mp4",
        file_size=10,
        status="ready",
        duration_seconds=1250.0,
    )
    row = Transcription(video=video, provider="fake", model="fake-1")
    db_session.add_all([user, video, row])
    db_session.commit()
    return row


class FakeMedia:
    """Replaces ffmpeg-based extraction and chunking with instant fakes that write files."""

    def __init__(
        self, monkeypatch, storage: LocalMediaStorage, *, duration=1250.0, chunks=(600, 600, 50)
    ):
        self.storage, self.duration, self.chunk_durations = storage, duration, chunks
        self.extract_calls = 0
        self.cleanup_calls = 0
        monkeypatch.setattr(pipeline, "extract_normalized_audio", self.extract)
        monkeypatch.setattr(pipeline, "split_audio", self.split)
        monkeypatch.setattr(pipeline, "cleanup_chunks", self.cleanup)

    def extract(self, source, storage, key, **kwargs):
        self.extract_calls += 1
        storage.save(io.BytesIO(b"mp3"), key)
        return ExtractedAudio(storage_key=key, size_bytes=3, duration_seconds=self.duration)

    def split(self, source, storage, transcription_id, *, total_seconds, chunk_seconds, **kwargs):
        assert total_seconds == self.duration and chunk_seconds == CHUNK_SECONDS
        chunks, start = [], 0.0
        for index, duration in enumerate(self.chunk_durations):
            key = f"transcription/{transcription_id}/chunks/{index:04d}.mp3"
            storage.save(io.BytesIO(b"chunk"), key)
            chunks.append(
                AudioChunk(
                    index=index, storage_key=key, start_seconds=start, duration_seconds=duration
                )
            )
            start += duration
        return chunks

    def cleanup(self, storage, transcription_id):
        self.cleanup_calls += 1


class SpyProvider(FakeProvider):
    """Records the transcription's status/progress at each call."""

    def __init__(self, db: Session, row: Transcription, **kwargs):
        super().__init__(**kwargs)
        self.db, self.row, self.observed = db, row, []

    def transcribe(self, request):
        self.db.refresh(self.row)
        self.observed.append((self.row.status, self.row.progress_percent))
        return super().transcribe(request)


def run(row: Transcription, db: Session, provider, storage, **kwargs) -> Transcription:
    settings = get_settings()
    settings.transcription_chunk_seconds = CHUNK_SECONDS
    return run_transcription(
        row.id,
        db,
        settings=settings,
        storage=storage,
        provider_factory=lambda s: provider,
        sleep=lambda _: None,
        **kwargs,
    )


def segments_of(db: Session, row: Transcription) -> list[TranscriptSegment]:
    return list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcription_id == row.id)
            .order_by(TranscriptSegment.sequence_index)
        )
    )


# --- happy path ----------------------------------------------------------------------------


def test_full_pipeline_completes_with_absolute_timestamps(
    monkeypatch, db_session, storage, transcription
):
    media = FakeMedia(monkeypatch, storage)
    provider = SpyProvider(db_session, transcription)

    result = run(transcription, db_session, provider, storage)

    assert result.status == "completed" and result.progress_percent == 100
    assert result.provider == "fake" and result.model == "fake-1"
    assert result.language == "en" and result.language_probability == 0.98
    assert result.started_at and result.completed_at and result.heartbeat_at
    assert result.audio_storage_key == f"transcription/{transcription.id}/normalized.mp3"
    assert result.audio_duration_seconds == 1250.0
    assert result.error_code is None and result.error_message is None

    segments = segments_of(db_session, transcription)
    assert [s.sequence_index for s in segments] == [0, 1, 2, 3, 4, 5]
    assert [(s.start_time, s.end_time) for s in segments] == [
        (0.0, 2.5),
        (2.5, 5.0),
        (600.0, 602.5),
        (602.5, 605.0),
        (1200.0, 1202.5),
        (1202.5, 1205.0),
    ]
    assert [s.text for s in segments] == ["Hello there.", "General Kenobi."] * 3
    assert all(s.speaker is None for s in segments)
    assert result.full_text == "Hello there. General Kenobi. " * 2 + "Hello there. General Kenobi."
    assert provider.observed == [("transcribing", 5), ("transcribing", 36), ("transcribing", 68)]
    assert media.extract_calls == 1 and media.cleanup_calls == 1


def test_previous_chunk_text_is_passed_as_prompt_only(
    monkeypatch, db_session, storage, transcription
):
    FakeMedia(monkeypatch, storage)
    provider = FakeProvider()

    run(transcription, db_session, provider, storage)

    prompts = [r.prompt for r in provider.requests]
    assert prompts[0] is None
    assert prompts[1] == "Hello there. General Kenobi." and prompts[2] == prompts[1]
    assert [r.language_hint for r in provider.requests] == [None, "en", "en"]
    assert [r.audio_path.name for r in provider.requests] == ["0000.mp3", "0001.mp3", "0002.mp3"]


def test_progress_is_monotonic_and_real(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage, chunks=(600,) * 8 + (50,))
    provider = SpyProvider(db_session, transcription)

    run(transcription, db_session, provider, storage)

    progress = [p for _, p in provider.observed]
    assert progress[0] == 5 and all(b > a for a, b in zip(progress, progress[1:], strict=False))
    assert max(progress) < 100 and transcription.progress_percent == 100


def test_single_chunk_short_video(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage, duration=42.0, chunks=(42.0,))

    result = run(transcription, db_session, FakeProvider(), storage)

    assert result.status == "completed"
    assert [(s.start_time, s.end_time) for s in segments_of(db_session, transcription)] == [
        (0.0, 2.5),
        (2.5, 5.0),
    ]


def test_silent_chunks_produce_a_completed_empty_transcript(
    monkeypatch, db_session, storage, transcription
):
    FakeMedia(monkeypatch, storage, chunks=(600, 50))

    result = run(transcription, db_session, FakeProvider(segments=(), language=None), storage)

    assert result.status == "completed" and result.full_text == ""
    assert segments_of(db_session, transcription) == []


# --- failures ----------------------------------------------------------------------------


def test_audio_extraction_failure(monkeypatch, db_session, storage, transcription):
    media = FakeMedia(monkeypatch, storage)

    def failing_extract(*a, **k):
        raise AudioExtractionError("no_audio_stream", "The video has no audio track")

    monkeypatch.setattr(pipeline, "extract_normalized_audio", failing_extract)
    provider = FakeProvider()

    result = run(transcription, db_session, provider, storage)

    assert result.status == "failed"
    assert (result.error_code, result.error_message) == (
        "no_audio_stream",
        "The video has no audio track",
    )
    assert result.completed_at is not None and result.audio_storage_key is None
    assert provider.requests == [] and media.cleanup_calls == 1


def test_chunking_failure(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage)

    def failing_split(*a, **k):
        raise ChunkingError("chunk_failed", "Could not create audio chunk 2 (ffmpeg exit 1)")

    monkeypatch.setattr(pipeline, "split_audio", failing_split)

    result = run(transcription, db_session, FakeProvider(), storage)

    assert result.status == "failed" and result.error_code == "chunk_failed"


def test_non_retryable_provider_error_fails_immediately(
    monkeypatch, db_session, storage, transcription
):
    FakeMedia(monkeypatch, storage)
    calls = []

    class Broken(FakeProvider):
        def transcribe(self, request):
            calls.append(request)
            raise TranscriptionProviderError("openai_authentication", "OpenAI rejected the API key")

    result = run(transcription, db_session, Broken(), storage)

    assert result.status == "failed" and result.error_code == "openai_authentication"
    assert len(calls) == 1
    assert segments_of(db_session, transcription) == []


def test_retryable_error_is_retried_with_backoff_then_succeeds(
    monkeypatch, db_session, storage, transcription
):
    FakeMedia(monkeypatch, storage, chunks=(600,))
    attempts, sleeps = [], []

    class Flaky(FakeProvider):
        def transcribe(self, request):
            attempts.append(1)
            if len(attempts) < 3:
                raise TranscriptionProviderError(
                    "openai_rate_limited", "rate limit", retryable=True
                )
            return super().transcribe(request)

    settings = get_settings()
    settings.transcription_provider_max_attempts = 3
    settings.transcription_retry_backoff_seconds = 2.0
    result = run_transcription(
        transcription.id,
        db_session,
        settings=settings,
        storage=storage,
        provider_factory=lambda s: Flaky(),
        sleep=sleeps.append,
    )

    assert result.status == "completed" and len(attempts) == 3
    assert sleeps == [2.0, 4.0]


def test_retryable_error_exhausts_attempts(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage, chunks=(600,))
    attempts = []

    class AlwaysDown(FakeProvider):
        def transcribe(self, request):
            attempts.append(1)
            raise TranscriptionProviderError(
                "openai_unreachable", "Could not reach OpenAI", retryable=True
            )

    settings = get_settings()
    settings.transcription_provider_max_attempts = 3
    result = run_transcription(
        transcription.id,
        db_session,
        settings=settings,
        storage=storage,
        provider_factory=lambda s: AlwaysDown(),
        sleep=lambda _: None,
    )

    assert result.status == "failed" and result.error_code == "openai_unreachable"
    assert len(attempts) == 3


def test_failure_mid_way_keeps_no_partial_segments(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage)
    calls = []

    class FailsOnThird(FakeProvider):
        def transcribe(self, request):
            calls.append(1)
            if len(calls) == 3:
                raise TranscriptionProviderError("provider_failure", "boom")
            return super().transcribe(request)

    result = run(transcription, db_session, FailsOnThird(), storage)

    assert result.status == "failed"
    assert segments_of(db_session, transcription) == []
    assert result.full_text is None


def test_segments_beyond_chunk_duration_are_rejected(
    monkeypatch, db_session, storage, transcription
):
    FakeMedia(monkeypatch, storage, duration=50.0, chunks=(50.0,))
    provider = FakeProvider(
        segments=(ProviderSegment(0.0, 10.0, "ok"), ProviderSegment(10.0, 90.0, "too far"))
    )

    result = run(transcription, db_session, provider, storage)

    assert result.status == "failed" and result.error_code == "provider_output"
    assert "beyond" in result.error_message


def test_small_overrun_within_tolerance_is_accepted(
    monkeypatch, db_session, storage, transcription
):
    FakeMedia(monkeypatch, storage, duration=50.0, chunks=(50.0,))
    provider = FakeProvider(segments=(ProviderSegment(45.0, 51.0, "trailing"),))

    result = run(transcription, db_session, provider, storage)

    assert result.status == "completed"


def test_missing_video_file(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage)
    storage.delete(transcription.video.storage_key)
    provider = FakeProvider()

    result = run(transcription, db_session, provider, storage)

    assert result.status == "failed" and result.error_code == "video_unavailable"
    assert provider.requests == []


def test_video_not_ready(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage)
    transcription.video.status = "failed"
    db_session.commit()

    result = run(transcription, db_session, FakeProvider(), storage)

    assert result.status == "failed" and result.error_code == "video_not_ready"


def test_unexpected_exception_is_contained(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage)

    class Explodes(FakeProvider):
        def transcribe(self, request):
            raise ZeroDivisionError("math at /Users/dev/secret")

    result = run(transcription, db_session, Explodes(), storage)

    assert result.status == "failed" and result.error_code == "internal_error"
    assert "/Users" not in result.error_message


# --- idempotency / duplicate delivery -------------------------------------------------------


def test_completed_job_ignores_duplicate_delivery(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage, chunks=(600,))
    run(transcription, db_session, FakeProvider(), storage)
    completed_at = transcription.completed_at
    provider = FakeProvider()

    run(transcription, db_session, provider, storage)

    assert provider.requests == []
    assert transcription.status == "completed" and transcription.completed_at == completed_at
    assert len(segments_of(db_session, transcription)) == 2


def test_running_job_with_fresh_heartbeat_is_not_started_twice(
    monkeypatch, db_session, storage, transcription
):
    FakeMedia(monkeypatch, storage)
    transcription.status = "transcribing"
    transcription.heartbeat_at = datetime.now(UTC)
    db_session.commit()
    provider = FakeProvider()

    run(transcription, db_session, provider, storage)

    assert provider.requests == [] and transcription.status == "transcribing"


def test_stale_job_is_restarted_cleanly(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage, chunks=(600,))
    transcription.status = "transcribing"
    transcription.heartbeat_at = datetime.now(UTC) - timedelta(hours=2)
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0, end_time=1, text="old")
    )
    transcription.progress_percent = 40
    db_session.commit()
    assert is_stale(transcription, get_settings())

    result = run(transcription, db_session, FakeProvider(), storage)

    assert result.status == "completed"
    assert [s.text for s in segments_of(db_session, transcription)] == [
        "Hello there.",
        "General Kenobi.",
    ]


def test_failed_job_is_not_rerun_without_reset(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage)
    transcription.status = "failed"
    db_session.commit()
    provider = FakeProvider()

    run(transcription, db_session, provider, storage)

    assert provider.requests == [] and transcription.status == "failed"


def test_retry_after_reset_clears_old_segments(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage, chunks=(600,))
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0, end_time=1, text="stale")
    )
    transcription.error_code, transcription.error_message = "x", "old failure"
    db_session.commit()  # status is still queued, as the retry endpoint leaves it

    result = run(transcription, db_session, FakeProvider(), storage)

    assert result.status == "completed" and result.error_code is None
    assert [s.text for s in segments_of(db_session, transcription)] == [
        "Hello there.",
        "General Kenobi.",
    ]


def test_unknown_transcription_is_a_noop(db_session, storage):
    assert (
        run_transcription(
            uuid.uuid4(), db_session, storage=storage, provider_factory=lambda s: FakeProvider()
        )
        is None
    )


def test_is_stale_only_for_active_statuses():
    settings = get_settings()
    old = datetime.now(UTC) - timedelta(days=1)
    for status in ("queued", "completed", "failed"):
        assert not is_stale(Transcription(status=status, heartbeat_at=old), settings)
    assert is_stale(Transcription(status="extracting_audio", heartbeat_at=old), settings)
    assert not is_stale(
        Transcription(status="transcribing", heartbeat_at=datetime.now(UTC)), settings
    )


# --- Celery wiring -----------------------------------------------------------------------------


def test_celery_task_runs_pipeline_in_eager_mode(monkeypatch, db_session, storage, transcription):
    FakeMedia(monkeypatch, storage, chunks=(600,))
    monkeypatch.setattr(pipeline, "get_transcription_provider", lambda s: FakeProvider())
    monkeypatch.setattr(
        "app.workers.transcription_tasks.SessionLocal", lambda: _Reusable(db_session)
    )
    monkeypatch.setattr(get_settings(), "media_root", storage.root)

    transcribe_video.delay(str(transcription.id))

    db_session.refresh(transcription)
    assert transcription.status == "completed"


def test_celery_task_ignores_invalid_ids():
    transcribe_video.delay("not-a-uuid")  # must not raise


class _Reusable:
    """Context manager handing the test session to the task without closing it."""

    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


# --- real ffmpeg end to end (fake provider) ------------------------------------------------------


@requires_ffmpeg
def test_real_media_pipeline_end_to_end(db_session, storage, tmp_path, transcription):
    clip = generate_video(tmp_path / "clip.mp4", seconds=2, fps=25)
    storage.delete(transcription.video.storage_key)
    with clip.open("rb") as handle:
        storage.save(handle, transcription.video.storage_key)
    settings = get_settings()
    settings.transcription_chunk_seconds = 30
    # Segments must fit inside the real 2-second chunk.
    provider = FakeProvider(
        segments=(ProviderSegment(0.0, 0.9, "Hello"), ProviderSegment(0.9, 1.8, "there"))
    )

    result = run_transcription(
        transcription.id,
        db_session,
        settings=settings,
        storage=storage,
        provider_factory=lambda s: provider,
    )

    assert result.status == "completed", result.error_message
    assert result.audio_duration_seconds == pytest.approx(2.0, abs=0.3)
    assert storage.exists(result.audio_storage_key)
    assert not (storage.root / "transcription" / str(transcription.id) / "chunks").exists()
    assert len(segments_of(db_session, transcription)) == 2
