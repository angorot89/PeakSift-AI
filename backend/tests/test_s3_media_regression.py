"""The creator media flow with every persistent file in an S3 bucket.

Real FFmpeg, eager Celery, the real pipelines and an S3 bucket (moto, and a live
S3-compatible service such as MinIO when configured) as the media backend: a video upload
is probed and stored, a clip is rendered, a music track is uploaded, an edit is composed
with that music, and every one of them is served by the same owner-checked Range
endpoints. Afterwards the bucket holds exactly the final artifacts, MEDIA_ROOT holds
nothing, and no job leaves scratch files behind.
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ClipCandidate, ClipDetectionRun, Transcription, TranscriptSegment, Video
from app.services import storage as storage_module
from app.services.clip_render import pipeline as render_pipeline
from app.services.storage import S3StorageProvider
from app.services.workspace import work_root
from tests.audio_fixtures import tone
from tests.media_fixtures import generate_video, requires_ffmpeg
from tests.storage_backends import live_available, provider

PASSWORD = "correct horse battery"


class _Reusable:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


@pytest.fixture(params=["s3-moto", "s3-live"])
def bucket(request, monkeypatch, tmp_path, db_session: Session):
    """Every part of the application (API and workers) uses one S3 bucket: in-process
    (moto), or a live S3-compatible service when ``TEST_S3_*`` is configured."""
    if request.param == "s3-live" and not live_available():
        pytest.skip("TEST_S3_ENDPOINT_URL / credentials are not set")
    with provider(request.param, tmp_path, monkeypatch) as s3:
        monkeypatch.setattr(storage_module, "_cached", None)
        monkeypatch.setattr(storage_module, "storage_from_settings", lambda settings: s3)
        for task in ("clip_render_tasks", "clip_edit_tasks"):
            monkeypatch.setattr(f"app.workers.{task}.SessionLocal", lambda: _Reusable(db_session))
        fast = Settings(**{**get_settings().model_dump(), "clip_render_preset": "ultrafast"})
        monkeypatch.setattr(render_pipeline, "get_settings", lambda: fast)
        yield s3
        monkeypatch.setattr(storage_module, "_cached", None)


def objects(s3: S3StorageProvider) -> list[str]:
    listing = s3._client.list_objects_v2(Bucket=s3.bucket)
    return sorted(item["Key"] for item in listing.get("Contents", []))


def files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def candidate_for(db_session: Session, video: Video, *, start: float, end: float):
    transcription = Transcription(video=video, provider="fake", model="fake-1", status="completed")
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0.0, end_time=end, text="words")
    )
    run = ClipDetectionRun(
        video=video, transcription=transcription, transcript_fingerprint="f" * 64,
        provider="ollama", model="llama3.2:3b", config={}, status="completed",
    )  # fmt: skip
    db_session.add_all([transcription, run])
    db_session.flush()
    candidate = ClipCandidate(
        run=run, video_id=video.id, start_time=start, end_time=end, duration_seconds=end - start,
        title="Bucket cut", hook="h", rationale="r", category="story", transcript_excerpt="words",
        overall_score=80, hook_score=80, entertainment_score=80, clarity_score=80,
        payoff_score=80, completeness_score=80, rank=1,
    )  # fmt: skip
    db_session.add(candidate)
    db_session.commit()
    return run, candidate


def assert_range_served(client: TestClient, url: str, size: int) -> bytes:
    full = client.get(url)
    assert full.status_code == 200 and len(full.content) == size, full.text[:200]
    part = client.get(url, headers={"Range": "bytes=10-109"})
    assert part.status_code == 206 and part.content == full.content[10:110]
    assert part.headers["content-range"] == f"bytes 10-109/{size}"
    suffix = client.get(url, headers={"Range": "bytes=-64"})
    assert suffix.status_code == 206 and suffix.content == full.content[-64:]
    assert client.get(url, headers={"Range": f"bytes={size}-"}).status_code == 416
    return full.content


@requires_ffmpeg
def test_the_media_flow_runs_entirely_on_object_storage(
    bucket, client: TestClient, db_session: Session, tmp_path: Path
):
    media_root = Path(get_settings().media_root)
    before_media = files_under(media_root)
    assert (
        client.post(
            "/auth/register", json={"email": "bucket@example.com", "password": PASSWORD}
        ).status_code
        == 201
    )
    project_id = client.post("/projects", json={"name": "Bucket"}).json()["id"]

    # Upload: spooled, probed and stored in the bucket.
    source = generate_video(tmp_path / "source.mp4", seconds=6.0)
    uploaded = client.post(
        f"/projects/{project_id}/videos",
        files={"file": ("source.mp4", source.read_bytes(), "video/mp4")},
    )
    assert uploaded.status_code == 201 and uploaded.json()["status"] == "ready", uploaded.text
    video = db_session.get(Video, uuid.UUID(uploaded.json()["id"]))
    assert bucket.exists(video.storage_key)
    served = assert_range_served(client, f"/videos/{video.id}/content", video.file_size)
    assert served == source.read_bytes()

    # Clip: the source is fetched into the job workspace, the render stored in the bucket.
    run, candidate = candidate_for(db_session, video, start=1.0, end=4.0)
    clip_url = (
        f"/projects/{project_id}/videos/{video.id}/clip-detection/{run.id}"
        f"/candidates/{candidate.id}/clip"
    )
    assert client.post(clip_url).status_code == 201
    clip = client.get(clip_url).json()
    assert clip["status"] == "ready", clip
    assert_range_served(client, f"/clips/{clip['id']}/content", clip["file_size"])

    # Music: validated from the spool, stored only after it passed.
    music = tone(tmp_path / "music.mp3", "0.3*sin(2*PI*220*t)", 5.0)
    asset = client.post(
        f"/projects/{project_id}/audio-assets",
        files={"file": ("music.mp3", music.read_bytes(), "audio/mpeg")},
        data={"kind": "music"},
    )
    assert asset.status_code == 201, asset.text
    asset = asset.json()
    assert_range_served(
        client, f"/projects/{project_id}/audio-assets/{asset['id']}/content", asset["file_size"]
    )

    # Edit: clip and music fetched from the bucket, the short stored there.
    edits = f"/projects/{project_id}/videos/{video.id}/clips/{clip['id']}/edits"
    created = client.post(
        edits, json={"layout": "center_crop", "audio": {"music": {"asset_id": asset["id"]}}}
    )
    assert created.status_code == 201, created.text
    edit = client.get(f"{edits}/{created.json()['id']}").json()
    assert edit["status"] == "ready", edit
    assert (edit["width"], edit["height"]) == (1080, 1920) and edit["audio_codec"] == "aac"
    short = assert_range_served(client, f"/edits/{edit['id']}/content", edit["file_size"])
    assert client.get(f"/edits/{edit['id']}/download").content == short

    # The bucket holds exactly the final artifacts; nothing went to MEDIA_ROOT; no job
    # left scratch files behind.
    assert objects(bucket) == sorted(
        [
            video.storage_key,
            f"clips/{clip['id']}/clip.mp4",
            f"edits/{edit['id']}/edited.mp4",
            next(k for k in objects(bucket) if k.startswith("audio/")),
        ]
    )
    assert files_under(media_root) == before_media
    leftovers = [p for p in files_under(work_root(get_settings())) if str(clip["id"]) in str(p)
                 or str(edit["id"]) in str(p) or "uploads" in p.parts]  # fmt: skip
    assert leftovers == []

    # A ready artifact whose object vanished from the bucket is reported, not served.
    bucket.delete(f"edits/{edit['id']}/edited.mp4")
    assert client.get(f"/edits/{edit['id']}/content").status_code == 404
    assert client.get(f"{edits}/{edit['id']}").json()["status"] == "failed"
