import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Project, User, Video, VideoStatus
from app.services import video_processing
from app.services.ffprobe import ProbeError, VideoMetadata
from app.services.storage import LocalStorageProvider
from tests.media_fixtures import generate_video, requires_ffmpeg

PASSWORD = "correct horse battery"
READY_METADATA = VideoMetadata(
    duration_seconds=120.5, width=1280, height=720, fps=29.97, video_codec="h264", audio_codec="aac"
)


def stored_video(
    db_session: Session, storage: LocalStorageProvider, content: bytes = b"data"
) -> Video:
    user = User(email="creator@example.com", password_hash="x")
    project = Project(name="P", owner=user)
    key = storage.generate_key("mp4")
    storage.save(io.BytesIO(content), key)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=key,
        content_type="video/mp4",
        file_size=len(content),
    )
    db_session.add_all([user, video])
    db_session.commit()
    return video


@pytest.fixture
def storage() -> LocalStorageProvider:
    return LocalStorageProvider(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalStorageProvider):
    yield
    for path in storage.root.rglob("*"):
        if path.is_file():
            path.unlink()


# --- state transitions (probe mocked) -----


def test_successful_probe_marks_video_ready(db_session: Session, storage, monkeypatch):
    video = stored_video(db_session, storage)
    monkeypatch.setattr(video_processing, "probe", lambda *a, **k: READY_METADATA)

    result = video_processing.process_video_metadata(db_session, storage, video)

    assert result.status == VideoStatus.READY == "ready"
    assert result.error_message is None
    assert (result.width, result.height, result.fps) == (1280, 720, 29.97)
    assert result.duration_seconds == 120.5
    assert (result.video_codec, result.audio_codec) == ("h264", "aac")
    db_session.expire_all()
    assert db_session.get(Video, video.id).status == "ready"


def test_probe_error_marks_video_failed_with_safe_message(
    db_session: Session, storage, monkeypatch
):
    video = stored_video(db_session, storage)

    def failing_probe(*a, **k):
        raise ProbeError("ffprobe could not read the file (exit code 1)")

    monkeypatch.setattr(video_processing, "probe", failing_probe)

    result = video_processing.process_video_metadata(db_session, storage, video)

    assert result.status == "failed"
    assert result.error_message == "ffprobe could not read the file (exit code 1)"
    assert str(storage.root) not in result.error_message
    assert result.duration_seconds is None


def test_unexpected_exception_marks_failed_instead_of_raising(db_session, storage, monkeypatch):
    video = stored_video(db_session, storage)

    def exploding_probe(*a, **k):
        raise RuntimeError("boom with /local/path")

    monkeypatch.setattr(video_processing, "probe", exploding_probe)

    result = video_processing.process_video_metadata(db_session, storage, video)

    assert result.status == "failed"
    assert "/local/path" not in result.error_message


def test_probe_receives_configured_binary_and_timeout(db_session, storage, monkeypatch):
    video = stored_video(db_session, storage)
    monkeypatch.setattr(get_settings(), "ffprobe_path", "/custom/ffprobe")
    monkeypatch.setattr(get_settings(), "ffprobe_timeout_seconds", 3.5)
    seen: dict = {}

    def fake_probe(path, *, ffprobe_path, timeout_seconds):
        seen.update(path=path, ffprobe_path=ffprobe_path, timeout_seconds=timeout_seconds)
        return READY_METADATA

    monkeypatch.setattr(video_processing, "probe", fake_probe)

    video_processing.process_video_metadata(db_session, storage, video)

    assert seen == {
        "path": storage.path_for(video.storage_key),
        "ffprobe_path": "/custom/ffprobe",
        "timeout_seconds": 3.5,
    }


def test_error_message_is_truncated(db_session, storage, monkeypatch):
    video = stored_video(db_session, storage)

    def long_failure(*a, **k):
        raise ProbeError("x" * 2000)

    monkeypatch.setattr(video_processing, "probe", long_failure)

    result = video_processing.process_video_metadata(db_session, storage, video)

    assert len(result.error_message) == 500


# --- end to end through the upload endpoint (real ffprobe) ---------------------------


def sign_up_with_project(client: TestClient) -> str:
    assert (
        client.post(
            "/auth/register", json={"email": "o@example.com", "password": PASSWORD}
        ).status_code
        == 201
    )
    return client.post("/projects", json={"name": "Stream"}).json()["id"]


@requires_ffmpeg
def test_upload_of_real_video_becomes_ready(client: TestClient, db_session: Session, tmp_path):
    project_id = sign_up_with_project(client)
    clip = generate_video(tmp_path / "clip.mp4", seconds=1, fps=30)

    response = client.post(
        f"/projects/{project_id}/videos",
        files={"file": ("my stream.mp4", clip.read_bytes(), "video/mp4")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready"
    video = db_session.scalar(select(Video).where(Video.id == uuid.UUID(response.json()["id"])))
    assert (video.width, video.height, video.fps) == (64, 64, 30.0)
    assert video.duration_seconds == pytest.approx(1.0, abs=0.2)
    assert (video.video_codec, video.audio_codec) == ("h264", "aac")
    assert video.error_message is None


@requires_ffmpeg
def test_upload_of_fake_video_becomes_failed(client: TestClient, db_session: Session):
    project_id = sign_up_with_project(client)

    response = client.post(
        f"/projects/{project_id}/videos",
        files={"file": ("broken.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048, "video/mp4")},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    video = db_session.scalar(select(Video).where(Video.id == uuid.UUID(response.json()["id"])))
    assert video.error_message
    assert str(get_settings().media_root) not in video.error_message
    assert video.width is None
