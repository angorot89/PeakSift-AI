"""End-to-end clip generation with real FFmpeg and no AI provider:

upload a generated video through the API → (persisted candidate) → POST generate → eager
Celery runs the real render → status ready → Range-streamed preview and download → the
served bytes are a valid H.264/AAC MP4 of the requested length → no temp files remain.
Required in CI (REQUIRE_FFMPEG=1); skipped locally without ffmpeg.
"""

import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import clips as clips_api
from app.core.config import Settings, get_settings
from app.models import ClipCandidate, ClipDetectionRun, Transcription, TranscriptSegment, Video
from app.services.clip_render import pipeline
from app.services.ffprobe import probe
from app.services.storage import LocalStorageProvider
from tests.media_fixtures import generate_video, requires_ffmpeg

PASSWORD = "correct horse battery"


class _Reusable:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


@pytest.fixture
def storage() -> LocalStorageProvider:
    return LocalStorageProvider(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalStorageProvider):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


@pytest.fixture
def wired(monkeypatch, db_session: Session):
    """Real enqueue (eager Celery) and the real renderer; the worker shares the test session."""
    monkeypatch.setattr("app.workers.clip_render_tasks.SessionLocal", lambda: _Reusable(db_session))
    settings = Settings(**{**get_settings().model_dump(), "clip_render_preset": "ultrafast"})
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(clips_api, "get_settings", lambda: settings)


def persisted_candidate(
    client: TestClient, db_session: Session, source: Path, *, start: float, end: float
) -> str:
    """Upload a real video through the API, then persist a completed run with one candidate."""
    assert (
        client.post(
            "/auth/register", json={"email": "render@example.com", "password": PASSWORD}
        ).status_code
        == 201
    )
    project_id = client.post("/projects", json={"name": "Render"}).json()["id"]
    response = client.post(
        f"/projects/{project_id}/videos",
        files={"file": ("source.mp4", source.read_bytes(), "video/mp4")},
    )
    assert response.status_code == 201 and response.json()["status"] == "ready", response.text
    video = db_session.get(Video, uuid.UUID(response.json()["id"]))
    transcription = Transcription(video=video, provider="fake", model="fake-1", status="completed")
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0.0, end_time=end, text="words")
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
    db_session.add_all([transcription, run])
    db_session.flush()
    candidate = ClipCandidate(
        run=run,
        video_id=video.id,
        start_time=start,
        end_time=end,
        duration_seconds=end - start,
        title="Integration: the cut",
        hook="h",
        rationale="r",
        category="story",
        transcript_excerpt="words",
        overall_score=80,
        hook_score=80,
        entertainment_score=80,
        clarity_score=80,
        payoff_score=80,
        completeness_score=80,
        rank=1,
    )
    db_session.add(candidate)
    db_session.commit()
    return (
        f"/projects/{project_id}/videos/{video.id}/clip-detection/{run.id}"
        f"/candidates/{candidate.id}/clip"
    )


@requires_ffmpeg
def test_generate_render_stream_and_download_a_real_clip(
    wired, client, db_session, storage, tmp_path
):
    source = generate_video(tmp_path / "source.mp4", seconds=6.0)
    url = persisted_candidate(client, db_session, source, start=2.0, end=4.5)

    started = client.post(url)
    assert started.status_code == 201
    clip_id = started.json()["id"]

    # Eager Celery rendered during the request; the row is ready with validated metadata.
    clip = client.get(url).json()
    assert clip["status"] == "ready" and clip["progress_percent"] == 100, clip
    assert clip["video_codec"] == "h264" and clip["audio_codec"] == "aac"
    assert (clip["width"], clip["height"]) == (64, 64)
    assert clip["file_size"] and clip["file_size"] > 0

    full = client.get(f"/clips/{clip_id}/content")
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    assert int(full.headers["content-length"]) == clip["file_size"] == len(full.content)

    part = client.get(f"/clips/{clip_id}/content", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == full.content[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{clip['file_size']}"
    assert (
        client.get(f"/clips/{clip_id}/content", headers={"Range": "bytes=99999999-"}).status_code
        == 416
    )

    download = client.get(f"/clips/{clip_id}/download")
    assert download.status_code == 200 and download.content == full.content
    assert download.headers["content-disposition"].startswith(
        'attachment; filename="integration-the-cut-'
    )

    with tempfile.NamedTemporaryFile(suffix=".mp4") as served:
        served.write(download.content)
        served.flush()
        meta = probe(Path(served.name))
    assert meta.video_codec == "h264" and meta.audio_codec == "aac"
    assert abs(meta.duration_seconds - 2.5) <= 1.0

    clip_dir = storage.root / "clips" / clip_id
    assert sorted(p.name for p in clip_dir.iterdir()) == ["clip.mp4"]  # no temp files remain


@requires_ffmpeg
def test_failed_render_leaves_nothing_and_retry_recovers(
    wired, client, db_session, storage, tmp_path, monkeypatch
):
    source = generate_video(tmp_path / "source.mp4", seconds=4.0)
    url = persisted_candidate(client, db_session, source, start=1.0, end=3.0)

    broken = Settings(**{**get_settings().model_dump(), "ffmpeg_path": str(tmp_path / "no-ffmpeg")})
    monkeypatch.setattr(pipeline, "get_settings", lambda: broken)
    clip_id = client.post(url).json()["id"]
    failed = client.get(url).json()
    assert failed["status"] == "failed" and failed["error_code"] == "ffmpeg_missing"
    assert not (storage.root / "clips" / clip_id).exists()
    assert client.get(f"/clips/{clip_id}/content").status_code == 404

    fixed = Settings(**{**get_settings().model_dump(), "clip_render_preset": "ultrafast"})
    monkeypatch.setattr(pipeline, "get_settings", lambda: fixed)
    retried = client.post(f"{url}/retry")
    assert retried.status_code == 200
    assert client.get(url).json()["status"] == "ready"
    assert client.get(f"/clips/{clip_id}/content").status_code == 200
    assert sorted(p.name for p in (storage.root / "clips" / clip_id).iterdir()) == ["clip.mp4"]
