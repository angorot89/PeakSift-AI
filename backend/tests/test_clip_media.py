import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.media_streaming import content_disposition
from app.core.config import get_settings
from app.models import (
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    Project,
    Transcription,
    User,
    Video,
)
from app.services.clip_render.storage import ClipArtifactStore, clip_storage_key
from app.services.storage import LocalMediaStorage

PASSWORD = "correct horse battery"
CONTENT = bytes(range(256)) * 20  # 5120 distinguishable bytes


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


def sign_up(client: TestClient, email: str) -> None:
    assert (
        client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )


def make_clip(
    db_session: Session,
    storage: LocalMediaStorage,
    email: str,
    *,
    status: str = "ready",
    title: str = "That Was Crazy!",
    write_file: bool = True,
) -> Clip:
    user = db_session.scalar(select(User).where(User.email == email))
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=10,
        status="ready",
        duration_seconds=300.0,
    )
    transcription = Transcription(video=video, provider="fake", model="fake-1", status="completed")
    run = ClipDetectionRun(
        video=video,
        transcription=transcription,
        transcript_fingerprint="f" * 64,
        provider="ollama",
        model="llama3.2:3b",
        config={},
        status="completed",
    )
    db_session.add_all([project, video, transcription, run])
    db_session.flush()
    candidate = ClipCandidate(
        run=run,
        video_id=video.id,
        start_time=30.0,
        end_time=50.0,
        duration_seconds=20.0,
        title=title,
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
        start_time=30.0,
        end_time=50.0,
        duration_seconds=20.0,
        status=status,
    )
    db_session.add_all([candidate, clip])
    db_session.flush()
    if status == "ready":
        clip.storage_key = clip_storage_key(clip.id)
        clip.file_size = len(CONTENT)
        if write_file:
            store = ClipArtifactStore(storage)
            store.temp_path(clip.id).write_bytes(CONTENT)
            store.finalize(clip.id)
    db_session.commit()
    return clip


def content_url(clip: Clip) -> str:
    return f"/clips/{clip.id}/content"


def download_url(clip: Clip) -> str:
    return f"/clips/{clip.id}/download"


# --- access control ----------------------------------------------------------------------------


def test_anonymous_requests_are_401(client: TestClient):
    clip_id = uuid.uuid4()
    assert client.get(f"/clips/{clip_id}/content").status_code == 401
    assert client.get(f"/clips/{clip_id}/download").status_code == 401


def test_other_user_gets_404_and_no_bytes(client, db_session, storage):
    sign_up(client, "alice@example.com")
    clip = make_clip(db_session, storage, "alice@example.com")
    client.cookies.clear()
    sign_up(client, "bob@example.com")
    for url in (content_url(clip), download_url(clip)):
        response = client.get(url)
        assert response.status_code == 404 and CONTENT[:16] not in response.content


def test_unknown_clip_is_404(client, db_session, storage):
    sign_up(client, "owner@example.com")
    assert client.get(f"/clips/{uuid.uuid4()}/content").status_code == 404
    assert client.get("/clips/not-a-uuid/content").status_code == 422


@pytest.mark.parametrize("status", ["queued", "rendering", "validating", "failed"])
def test_clip_that_is_not_ready_is_404(client, db_session, storage, status):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com", status=status)
    assert client.get(content_url(clip)).status_code == 404
    assert client.get(download_url(clip)).status_code == 404


def test_ready_clip_with_missing_artifact_is_404_not_500(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com", write_file=False)
    response = client.get(content_url(clip))
    assert response.status_code == 404 and response.json()["detail"] == "Clip file not found"


def test_corrupted_storage_key_cannot_escape_the_media_root(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")
    clip.storage_key = "../../../etc/passwd"
    db_session.commit()
    assert client.get(content_url(clip)).status_code == 404


# --- preview -----------------------------------------------------------------------------------


def test_full_preview_streams_inline_with_range_support(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")

    response = client.get(content_url(clip))

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(CONTENT))
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "content-range" not in response.headers


def test_byte_range_returns_206(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")
    response = client.get(content_url(clip), headers={"Range": "bytes=100-199"})
    assert response.status_code == 206
    assert response.content == CONTENT[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{len(CONTENT)}"
    assert response.headers["content-length"] == "100"


def test_open_ended_and_suffix_ranges(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")
    tail = client.get(content_url(clip), headers={"Range": "bytes=5000-"})
    assert tail.status_code == 206 and tail.content == CONTENT[5000:]
    suffix = client.get(content_url(clip), headers={"Range": "bytes=-20"})
    assert suffix.status_code == 206 and suffix.content == CONTENT[-20:]
    assert (
        suffix.headers["content-range"]
        == f"bytes {len(CONTENT) - 20}-{len(CONTENT) - 1}/{len(CONTENT)}"
    )


@pytest.mark.parametrize("header", ["bytes=999999-", "bytes=6000-7000", "bytes=50-10"])
def test_unsatisfiable_range_is_416(client, db_session, storage, header):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")
    response = client.get(content_url(clip), headers={"Range": header})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(CONTENT)}"


def test_malformed_or_multi_range_serves_everything(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")
    for header in ("bytes=0-10,20-30", "items=0-10", "bytes=abc"):
        response = client.get(content_url(clip), headers={"Range": header})
        assert response.status_code == 200 and response.content == CONTENT


# --- download -----------------------------------------------------------------------------------


def test_download_is_an_attachment_with_a_safe_name(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")

    response = client.get(download_url(clip))

    assert response.status_code == 200 and response.content == CONTENT
    disposition = response.headers["content-disposition"]
    expected = f"that-was-crazy-{str(clip.id)[:8]}.mp4"
    assert disposition == f"attachment; filename=\"{expected}\"; filename*=UTF-8''{expected}"
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize(
    "title",
    # Titles a candidate can really hold: PostgreSQL forbids NUL and the column is 120 chars
    # (NUL and over-long input are covered by the safe_download_filename unit tests).
    [
        '../../etc/passwd "x"',
        "Été\x1b à\r\nParis\t",
        "مرحبا بكم",
        "x" * 120,
        'quote " and \\ slash',
    ],
)
def test_download_name_is_safe_for_hostile_titles(client, db_session, storage, title):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com", title=title)
    disposition = client.get(download_url(clip)).headers["content-disposition"]
    filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
    assert filename.endswith(f"{str(clip.id)[:8]}.mp4")
    assert "/" not in filename and "\\" not in filename and ".." not in filename
    assert all(ch.isascii() and ch.isprintable() for ch in disposition)
    assert len(filename) <= 73


def test_download_supports_ranges_too(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com")
    response = client.get(download_url(clip), headers={"Range": "bytes=0-9"})
    assert response.status_code == 206 and response.content == CONTENT[:10]


def test_responses_never_leak_paths_or_keys(client, db_session, storage):
    sign_up(client, "owner@example.com")
    clip = make_clip(db_session, storage, "owner@example.com", write_file=False)
    response = client.get(content_url(clip))
    text = response.text + " ".join(response.headers.values())
    assert (
        str(storage.root) not in text
        and "clips/" not in text
        and str(clip.id) + "/clip" not in text
    )


# --- shared helper ------------------------------------------------------------------------------


def test_content_disposition_helper_variants():
    assert content_disposition("a.mp4").startswith("inline;")
    assert content_disposition("a.mp4", attachment=True).startswith("attachment;")
    assert 'filename="clip t .mp4"' in content_disposition('clip "été" 🎬.mp4')


def test_source_video_streaming_still_works_through_the_shared_helper(client, storage):
    sign_up(client, "owner@example.com")
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    video_id = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", CONTENT, "video/mp4")}
    ).json()["id"]
    response = client.get(f"/videos/{video_id}/content", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206 and response.content == CONTENT[:10]
