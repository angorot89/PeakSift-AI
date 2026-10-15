"""Owner-only preview of uploaded audio: full and Range responses, safe headers, no paths."""

import uuid
from pathlib import Path

import pytest

from app.core.config import get_settings
from tests.media_fixtures import requires_ffmpeg
from tests.test_audio_assets_api import make_audio, upload
from tests.test_video_upload import create_project, sign_up

pytestmark = requires_ffmpeg


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in Path(get_settings().media_root).rglob("*"):
        if path.is_file():
            path.unlink()


@pytest.fixture
def asset(client, tmp_path):
    sign_up(client, f"listener-{uuid.uuid4().hex[:8]}@example.com")
    project = create_project(client)["id"]
    path = make_audio(tmp_path / "theme.mp3", seconds=3)
    body = upload(client, project, path, name="Thème d'été.mp3").json()
    return {"project": project, "id": body["id"], "bytes": path.read_bytes(),
            "url": f"/projects/{project}/audio-assets/{body['id']}/content"}  # fmt: skip


def test_the_owner_streams_the_whole_file_privately(client, asset):
    response = client.get(asset["url"])
    assert response.status_code == 200 and response.content == asset["bytes"]
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline;") and "filename*=UTF-8''Th%C3%A8me" in disposition
    assert get_settings().media_root.as_posix() not in str(response.headers)


def test_byte_ranges_for_seeking(client, asset):
    size = len(asset["bytes"])
    part = client.get(asset["url"], headers={"Range": "bytes=10-99"})
    assert part.status_code == 206 and part.content == asset["bytes"][10:100]
    assert part.headers["content-range"] == f"bytes 10-99/{size}"
    tail = client.get(asset["url"], headers={"Range": "bytes=-50"})
    assert tail.status_code == 206 and tail.content == asset["bytes"][-50:]
    beyond = client.get(asset["url"], headers={"Range": f"bytes={size + 5}-"})
    assert beyond.status_code == 416 and beyond.headers["content-range"] == f"bytes */{size}"


def test_other_users_and_anonymous_requests_cannot_listen(client, asset):
    client.post("/auth/logout")
    assert client.get(asset["url"]).status_code == 401
    sign_up(client, f"other-{uuid.uuid4().hex[:8]}@example.com")
    assert client.get(asset["url"]).status_code == 404
    own = create_project(client, "Mine")["id"]
    assert client.get(f"/projects/{own}/audio-assets/{asset['id']}/content").status_code == 404


def test_a_missing_file_is_a_plain_404(client, asset):
    for path in Path(get_settings().media_root).rglob("*.mp3"):
        path.unlink()
    response = client.get(asset["url"])
    assert response.status_code == 404 and "media" not in response.text.lower()
