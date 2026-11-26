"""Quick start: one upload becomes a named project that transcribes and then finds moments."""

import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import quick_start as api
from app.core.config import Settings, get_settings
from app.models import ClipDetectionRun, Project, Transcription, TranscriptSegment, Video
from app.services.clip_detection import autostart
from app.services.quick_start import FALLBACK_NAME, project_name
from app.workers import transcription_tasks as tasks
from app.workers.dispatch import JobQueueUnavailable
from tests.media_fixtures import generate_video, requires_ffmpeg

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch, db_session):
    """Record what would be queued; the fencing token must already be on the row."""
    queued: list[uuid.UUID] = []

    def fake_enqueue(transcription_id, *, task_id):
        row = db_session.get(Transcription, transcription_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append(transcription_id)
        return task_id

    monkeypatch.setattr(api, "enqueue_transcription", fake_enqueue)
    return queued


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in Path(get_settings().media_root).rglob("*"):
        if path.is_file():
            path.unlink()


def sign_up(client: TestClient, email: str = "owner@example.com") -> None:
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201


def post(client: TestClient, filename: str, content: bytes, **fields):
    return client.post(
        "/quick-start", files={"file": (filename, content, "video/mp4")}, data=fields
    )


def count(db_session: Session, model) -> int:
    return db_session.scalar(select(func.count()).select_from(model)) or 0


# --- the project's name ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "filename", "expected"),
    [
        (None, "Friday_stream-2026.09.28.mp4", "Friday stream 2026 09 28"),
        ("", "podcast ep 12.mov", "podcast ep 12"),
        ("  My interview  ", "raw.mp4", "My interview"),
        (None, "C:\\Users\\me\\Videos\\vlog.final.webm", "vlog final"),
        (None, "../../etc/passwd.mp4", "passwd"),
        (None, ".mp4", "mp4"),
        (None, "___.mp4", FALLBACK_NAME),
        (None, None, FALLBACK_NAME),
        (None, "حلقة_جديدة.mp4", "حلقة جديدة"),
    ],
)
def test_project_name(given, filename, expected):
    assert project_name(given, filename) == expected


def test_project_name_is_bounded_and_has_no_control_characters():
    assert len(project_name(None, "a" * 500 + ".mp4")) == 200
    assert project_name("line\none\ttwo", None) == "line one two"


# --- the endpoint -----------------------------------------------------------------------


def test_requires_authentication(client: TestClient):
    assert post(client, "s.mp4", MP4_BYTES).status_code == 401


@requires_ffmpeg
def test_one_upload_becomes_a_working_project(client, db_session, fake_queue, tmp_path):
    sign_up(client)
    source = generate_video(tmp_path / "Friday_stream-ep.12.mp4", seconds=1.0)

    response = post(client, source.name, source.read_bytes())

    assert response.status_code == 201
    body = response.json()
    assert body["project"]["name"] == "Friday stream ep 12"
    assert body["project"]["market"] == "global"
    assert body["video"]["status"] == "ready"
    assert body["video"]["project_id"] == body["project"]["id"]
    assert body["transcription_started"] is True

    transcription = db_session.get(Video, uuid.UUID(body["video"]["id"])).transcription
    assert transcription.status == "queued"
    assert transcription.auto_find_moments is True
    assert fake_queue == [transcription.id]

    # The ordinary project pages see the same job, and that moments will follow by themselves.
    status = client.get(
        f"/projects/{body['project']['id']}/videos/{body['video']['id']}/transcription"
    ).json()
    assert status["auto_find_moments"] is True


@requires_ffmpeg
def test_typed_name_and_market_win(client, db_session, tmp_path):
    sign_up(client)
    source = generate_video(tmp_path / "raw.mp4", seconds=1.0)

    body = post(client, source.name, source.read_bytes(), name=" Vox pop Casa ", market="ma").json()

    assert body["project"]["name"] == "Vox pop Casa"
    assert body["project"]["market"] == "ma"


def test_a_refused_upload_leaves_no_project(client, db_session, fake_queue):
    sign_up(client)

    response = post(client, "notes.txt", b"hello")

    assert response.status_code in (400, 415)
    assert count(db_session, Project) == 0
    assert count(db_session, Video) == 0
    assert fake_queue == []


def test_unknown_market_is_refused_before_anything_is_stored(client, db_session):
    sign_up(client)

    assert post(client, "s.mp4", MP4_BYTES, market="zz").status_code == 422
    assert count(db_session, Project) == 0


def test_an_unreadable_video_keeps_the_project_but_starts_nothing(client, db_session, fake_queue):
    """The creator lands on the project, which already explains a failed source and re-upload."""
    sign_up(client)

    response = post(client, "broken.mp4", MP4_BYTES)

    assert response.status_code == 201
    body = response.json()
    assert body["video"]["status"] == "failed"
    assert body["transcription_started"] is False
    assert count(db_session, Transcription) == 0
    assert fake_queue == []


@requires_ffmpeg
def test_queue_outage_leaves_no_orphan_job(client, db_session, monkeypatch, tmp_path):
    sign_up(client)
    source = generate_video(tmp_path / "s.mp4", seconds=1.0)

    def down(transcription_id, *, task_id):
        raise JobQueueUnavailable("broker down")

    monkeypatch.setattr(api, "enqueue_transcription", down)

    response = post(client, source.name, source.read_bytes())

    assert response.status_code == 201
    assert response.json()["transcription_started"] is False
    assert count(db_session, Transcription) == 0
    assert count(db_session, Project) == 1  # the upload is kept; the project shows "Transcribe"


# --- moments follow the transcript ----------------------------------------------------


def UP(name, model, settings) -> bool:  # noqa: N802 - reads as a constant at call sites
    return True


def local_settings(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update(
        openai_api_key=None,
        clip_detection_ollama_enabled=True,
        ollama_clip_models="llama3.2:3b,qwen2.5:7b",
    )
    base.update(overrides)
    return Settings(**base)


def transcribed_video(client: TestClient, db_session: Session, *, lines: int = 60) -> Video:
    sign_up(client)
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    video_id = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", MP4_BYTES, "video/mp4")}
    ).json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    video.status, video.error_message, video.duration_seconds = "ready", None, lines * 5.0
    transcription = Transcription(
        video=video,
        provider="faster_whisper",
        model="small",
        status="completed",
        progress_percent=100,
        auto_find_moments=True,
    )
    for i in range(lines):
        transcription.segments.append(
            TranscriptSegment(
                sequence_index=i, start_time=i * 5.0, end_time=(i + 1) * 5.0, text=f"line {i}"
            )
        )
    db_session.add(transcription)
    db_session.commit()
    return video


@pytest.fixture
def detection_queue(monkeypatch, db_session):
    queued: list[uuid.UUID] = []

    def fake_enqueue(run_id, *, task_id):
        row = db_session.get(ClipDetectionRun, run_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append(run_id)
        return task_id

    monkeypatch.setattr(autostart, "enqueue_clip_detection", fake_enqueue)
    return queued


def test_detection_starts_once_with_the_default_provider(client, db_session, detection_queue):
    video = transcribed_video(client, db_session)

    run = autostart.start_default_detection(db_session, video, local_settings(), reachable=UP)

    assert run is not None
    assert (run.provider, run.model, run.status) == ("ollama", "llama3.2:3b", "queued")
    assert run.transcription_id == video.transcription.id
    assert detection_queue == [run.id]

    # A second completion (a replayed task) never starts another run.
    assert (
        autostart.start_default_detection(db_session, video, local_settings(), reachable=UP) is None
    )
    assert count(db_session, ClipDetectionRun) == 1


def test_nothing_starts_without_a_provider(client, db_session, detection_queue):
    video = transcribed_video(client, db_session)
    settings = local_settings(clip_detection_ollama_enabled=False)

    assert autostart.start_default_detection(db_session, video, settings, reachable=UP) is None
    assert count(db_session, ClipDetectionRun) == 0


def test_an_unreachable_provider_is_skipped_for_the_next_one(client, db_session, detection_queue):
    video = transcribed_video(client, db_session)
    settings = local_settings(openai_api_key="sk-test", openai_clip_models="gpt-4o-mini")

    run = autostart.start_default_detection(
        db_session, video, settings, reachable=lambda name, model, s: name == "openai"
    )

    assert (run.provider, run.model) == ("openai", "gpt-4o-mini")


def test_nothing_starts_when_no_provider_is_reachable(client, db_session, detection_queue):
    video = transcribed_video(client, db_session)

    run = autostart.start_default_detection(
        db_session, video, local_settings(), reachable=lambda *a: False
    )

    assert run is None
    assert count(db_session, ClipDetectionRun) == 0


def test_a_provider_that_raises_while_probed_counts_as_unreachable(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(autostart, "get_clip_provider", boom)

    assert autostart.default_choice(local_settings()) is None


@pytest.mark.parametrize("status", ["queued", "transcribing", "failed"])
def test_nothing_starts_before_the_transcript_is_complete(
    client, db_session, detection_queue, status
):
    video = transcribed_video(client, db_session)
    video.transcription.status = status
    db_session.commit()

    assert (
        autostart.start_default_detection(db_session, video, local_settings(), reachable=UP) is None
    )
    assert detection_queue == []


def test_nothing_starts_for_an_empty_transcript(client, db_session, detection_queue):
    video = transcribed_video(client, db_session, lines=0)

    assert (
        autostart.start_default_detection(db_session, video, local_settings(), reachable=UP) is None
    )
    assert count(db_session, ClipDetectionRun) == 0


def test_a_busy_queue_leaves_no_run(client, db_session, monkeypatch):
    video = transcribed_video(client, db_session)

    def down(run_id, *, task_id):
        raise JobQueueUnavailable("broker down")

    monkeypatch.setattr(autostart, "enqueue_clip_detection", down)

    assert (
        autostart.start_default_detection(db_session, video, local_settings(), reachable=UP) is None
    )
    assert count(db_session, ClipDetectionRun) == 0


# --- the worker ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("auto", "status", "expected"),
    [(True, "completed", 1), (False, "completed", 0), (True, "failed", 0)],
)
def test_the_worker_starts_detection_only_for_a_flagged_completed_transcript(
    monkeypatch, auto, status, expected
):
    started = []
    finished = SimpleNamespace(auto_find_moments=auto, status=status, video=object())

    @contextmanager
    def session():
        yield SimpleNamespace(rollback=lambda: None)

    monkeypatch.setattr(tasks, "SessionLocal", session)
    monkeypatch.setattr(tasks, "run_transcription", lambda *a, **k: finished)
    monkeypatch.setattr(tasks, "start_default_detection", lambda db, video: started.append(video))

    tasks.transcribe_video.run(str(uuid.uuid4()))

    assert len(started) == expected


def test_a_detection_problem_never_fails_the_transcription_task(monkeypatch):
    finished = SimpleNamespace(auto_find_moments=True, status="completed", video=object())
    rolled_back = []

    @contextmanager
    def session():
        yield SimpleNamespace(rollback=lambda: rolled_back.append(True))

    def boom(db, video):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(tasks, "SessionLocal", session)
    monkeypatch.setattr(tasks, "run_transcription", lambda *a, **k: finished)
    monkeypatch.setattr(tasks, "start_default_detection", boom)

    tasks.transcribe_video.run(str(uuid.uuid4()))  # does not raise

    assert rolled_back == [True]
