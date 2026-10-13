import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Video

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024

EXPECTED_KEYS = {
    "id",
    "project_id",
    "original_filename",
    "content_type",
    "file_size",
    "duration_seconds",
    "width",
    "height",
    "fps",
    "video_codec",
    "audio_codec",
    "status",
    "error_message",
    "created_at",
    "updated_at",
}


def sign_up(client: TestClient, email: str) -> None:
    assert (
        client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )


def create_project(client: TestClient) -> str:
    return client.post("/projects", json={"name": "Stream"}).json()["id"]


def upload(client: TestClient, project_id: str, filename: str = "stream.mp4") -> dict:
    response = client.post(
        f"/projects/{project_id}/videos", files={"file": (filename, MP4_BYTES, "video/mp4")}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in Path(get_settings().media_root).rglob("*"):
        if path.is_file():
            path.unlink()


# --- authentication -----


def test_read_endpoints_require_authentication(client: TestClient):
    project_id, video_id = uuid.uuid4(), uuid.uuid4()

    assert client.get(f"/projects/{project_id}/videos").status_code == 401
    assert client.get(f"/projects/{project_id}/videos/{video_id}").status_code == 401


# --- listing -----


def test_list_is_empty_for_project_without_videos(client: TestClient):
    sign_up(client, "owner@example.com")
    project_id = create_project(client)

    response = client.get(f"/projects/{project_id}/videos")

    assert response.status_code == 200
    assert response.json() == []


def test_list_returns_own_videos_newest_first(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    project_id = create_project(client)
    older = upload(client, project_id, "older.mp4")
    newer = upload(client, project_id, "newer.mp4")
    # Tests run in one transaction where now() is constant; back-date explicitly.
    db_session.execute(
        update(Video)
        .where(Video.id == uuid.UUID(older["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(hours=1))
    )
    db_session.commit()
    db_session.expire_all()

    names = [v["original_filename"] for v in client.get(f"/projects/{project_id}/videos").json()]

    assert names == ["newer.mp4", "older.mp4"]
    assert newer["id"] != older["id"]


def test_list_is_scoped_to_the_project(client: TestClient):
    sign_up(client, "owner@example.com")
    first, second = create_project(client), create_project(client)
    upload(client, first, "first.mp4")

    assert [v["original_filename"] for v in client.get(f"/projects/{first}/videos").json()] == [
        "first.mp4"
    ]
    assert client.get(f"/projects/{second}/videos").json() == []


# --- detail -----


def test_detail_has_exactly_the_safe_fields(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    project_id = create_project(client)
    uploaded = upload(client, project_id)

    response = client.get(f"/projects/{project_id}/videos/{uploaded['id']}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == EXPECTED_KEYS
    assert body["id"] == uploaded["id"]
    assert body["project_id"] == project_id
    assert body["original_filename"] == "stream.mp4"
    assert body["file_size"] == len(MP4_BYTES)
    assert body["status"] in ("ready", "failed")
    # Nothing about the server's filesystem leaks.
    video = db_session.get(Video, uuid.UUID(uploaded["id"]))
    assert video.storage_key not in response.text
    assert str(get_settings().media_root) not in response.text
    assert "/" not in (body["error_message"] or "")


def test_detail_exposes_probe_metadata_when_present(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    project_id = create_project(client)
    uploaded = upload(client, project_id)
    db_session.execute(
        update(Video)
        .where(Video.id == uuid.UUID(uploaded["id"]))
        .values(
            status="ready",
            error_message=None,
            duration_seconds=8040.5,
            width=1920,
            height=1080,
            fps=29.97,
            video_codec="h264",
            audio_codec="aac",
        )
    )
    db_session.commit()
    db_session.expire_all()

    body = client.get(f"/projects/{project_id}/videos/{uploaded['id']}").json()

    assert body["status"] == "ready"
    assert body["error_message"] is None
    assert body["duration_seconds"] == 8040.5
    assert (body["width"], body["height"], body["fps"]) == (1920, 1080, 29.97)
    assert (body["video_codec"], body["audio_codec"]) == ("h264", "aac")


# --- ownership and existence -----


def test_other_user_cannot_list_or_read_videos(client: TestClient):
    sign_up(client, "alice@example.com")
    alices_project = create_project(client)
    alices_video = upload(client, alices_project)
    client.cookies.clear()
    sign_up(client, "bob@example.com")

    assert client.get(f"/projects/{alices_project}/videos").status_code == 404
    assert client.get(f"/projects/{alices_project}/videos/{alices_video['id']}").status_code == 404


def test_video_must_belong_to_the_project_in_the_url(client: TestClient):
    sign_up(client, "owner@example.com")
    first, second = create_project(client), create_project(client)
    video = upload(client, first)

    assert client.get(f"/projects/{second}/videos/{video['id']}").status_code == 404
    assert client.get(f"/projects/{first}/videos/{video['id']}").status_code == 200


def test_unknown_video_is_not_found(client: TestClient):
    sign_up(client, "owner@example.com")
    project_id = create_project(client)

    assert client.get(f"/projects/{project_id}/videos/{uuid.uuid4()}").status_code == 404


def test_malformed_video_id_is_rejected(client: TestClient):
    sign_up(client, "owner@example.com")
    project_id = create_project(client)

    assert client.get(f"/projects/{project_id}/videos/not-a-uuid").status_code == 422
