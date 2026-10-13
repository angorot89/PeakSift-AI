import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.video_content import content_disposition, parse_range
from app.core.config import get_settings

PASSWORD = "correct horse battery"
CONTENT = bytes(range(256)) * 10  # 2560 distinguishable bytes


def sign_up(client: TestClient, email: str) -> None:
    assert (
        client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )


def upload_video(
    client: TestClient, filename: str = "stream.mp4", content_type: str = "video/mp4"
) -> str:
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    response = client.post(
        f"/projects/{project_id}/videos", files={"file": (filename, CONTENT, content_type)}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in Path(get_settings().media_root).rglob("*"):
        if path.is_file():
            path.unlink()


# --- range parsing -----


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("", None),
        ("bytes=0-99", (0, 99)),
        ("bytes=100-", (100, 999)),
        ("bytes=-50", (950, 999)),
        ("bytes=-5000", (0, 999)),
        ("bytes=0-999999", (0, 999)),
        ("bytes=0-10,20-30", None),  # multiple ranges: serve everything
        ("bytes=abc", None),
        ("items=0-10", None),
        ("bytes=-", None),
    ],
)
def test_parse_range(header, expected):
    assert parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5000-6000", "bytes=50-10"])
def test_parse_range_unsatisfiable(header):
    with pytest.raises(HTTPException) as excinfo:
        parse_range(header, 1000)
    assert excinfo.value.status_code == 416
    assert excinfo.value.headers["Content-Range"] == "bytes */1000"


def test_parse_range_empty_file_serves_everything():
    assert parse_range("bytes=0-10", 0) is None


def test_content_disposition_is_inline_and_unicode_safe():
    value = content_disposition('clip "été" 🎬.mp4')
    assert value.startswith("inline;")
    assert 'filename="clip t .mp4"' in value  # non-ASCII dropped, quotes removed
    assert "filename*=UTF-8''clip%20%22%C3%A9t%C3%A9%22%20%F0%9F%8E%AC.mp4" in value


# --- access control -----


def test_content_requires_authentication(client: TestClient):
    assert client.get(f"/videos/{uuid.uuid4()}/content").status_code == 401


def test_owner_can_stream_full_content(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client)

    response = client.get(f"/videos/{video_id}/content")

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-length"] == str(len(CONTENT))
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"].startswith('inline; filename="stream.mp4"')
    assert "no-store" in response.headers["cache-control"]


def test_other_user_cannot_access_content(client: TestClient):
    sign_up(client, "alice@example.com")
    video_id = upload_video(client)
    client.cookies.clear()
    sign_up(client, "bob@example.com")

    assert client.get(f"/videos/{video_id}/content").status_code == 404


def test_unknown_video_is_not_found(client: TestClient):
    sign_up(client, "owner@example.com")

    assert client.get(f"/videos/{uuid.uuid4()}/content").status_code == 404


def test_missing_file_is_not_found_without_leaking_path(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client)
    for path in Path(get_settings().media_root).rglob("*"):
        if path.is_file():
            path.unlink()

    response = client.get(f"/videos/{video_id}/content")

    assert response.status_code == 404
    assert str(get_settings().media_root) not in response.text


def test_mov_uses_quicktime_content_type(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client, "clip.mov", "video/quicktime")

    assert client.get(f"/videos/{video_id}/content").headers["content-type"] == "video/quicktime"


# --- range requests -----


def test_range_request_returns_partial_content(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client)

    response = client.get(f"/videos/{video_id}/content", headers={"Range": "bytes=100-299"})

    assert response.status_code == 206
    assert response.content == CONTENT[100:300]
    assert response.headers["content-range"] == f"bytes 100-299/{len(CONTENT)}"
    assert response.headers["content-length"] == "200"
    assert response.headers["content-type"] == "video/mp4"


def test_open_ended_and_suffix_ranges(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client)
    url = f"/videos/{video_id}/content"

    tail = client.get(url, headers={"Range": "bytes=2500-"})
    assert tail.status_code == 206 and tail.content == CONTENT[2500:]
    assert tail.headers["content-range"] == f"bytes 2500-2559/{len(CONTENT)}"

    suffix = client.get(url, headers={"Range": "bytes=-16"})
    assert suffix.status_code == 206 and suffix.content == CONTENT[-16:]


def test_range_beyond_end_is_clamped(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client)

    response = client.get(f"/videos/{video_id}/content", headers={"Range": "bytes=0-999999"})

    assert response.status_code == 206
    assert response.content == CONTENT
    assert response.headers["content-range"] == f"bytes 0-{len(CONTENT) - 1}/{len(CONTENT)}"


def test_unsatisfiable_range(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client)

    response = client.get(f"/videos/{video_id}/content", headers={"Range": "bytes=999999-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(CONTENT)}"


def test_malformed_or_multi_range_serves_everything(client: TestClient):
    sign_up(client, "owner@example.com")
    video_id = upload_video(client)
    url = f"/videos/{video_id}/content"

    for header in ("bytes=abc", "bytes=0-10,20-30"):
        response = client.get(url, headers={"Range": header})
        assert response.status_code == 200
        assert response.content == CONTENT
