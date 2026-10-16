"""The private media HTTP contract does not depend on the storage backend.

The same owner-checked request sequence (full, ranged, suffix, open-ended and
unsatisfiable ranges, a foreign user) runs against a local directory and an S3 bucket; the
responses must be identical. A vanished object is a 404 on both, an outage a 503.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_storage
from app.main import app
from app.models import Video
from app.services.storage import StorageUnavailable
from tests.storage_backends import provider

PASSWORD = "correct horse battery"
CONTENT = bytes(range(256)) * 10  # 2560 distinguishable bytes
RANGES = [None, "bytes=0-99", "bytes=100-", "bytes=-50", "bytes=-5000", "bytes=2559-2559",
          "bytes=0-10,20-30", "bytes=2560-", "bytes=50-10"]  # fmt: skip


def sign_up(client: TestClient, email: str) -> None:
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201


def stored_video(client: TestClient, db_session, storage) -> tuple[str, str]:
    """A video row whose bytes live in ``storage`` (no upload pipeline involved)."""
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    key = storage.generate_key("mp4")
    storage.save(io.BytesIO(CONTENT), key)
    video = Video(
        project_id=uuid.UUID(project_id),
        original_filename="stream.mp4",
        storage_key=key,
        content_type="video/mp4",
        file_size=len(CONTENT),
    )
    db_session.add(video)
    db_session.commit()
    return str(video.id), key


def observe(client: TestClient, video_id: str) -> list[tuple]:
    seen = []
    for header in RANGES:
        response = client.get(
            f"/videos/{video_id}/content", headers={"Range": header} if header else {}
        )
        kept = ("content-range", "content-length", "accept-ranges", "cache-control",
                "content-type", "content-disposition")  # fmt: skip
        seen.append(
            (header, response.status_code, {h: response.headers.get(h) for h in kept},
             response.content)
        )  # fmt: skip
    return seen


@pytest.fixture
def run(client, db_session, tmp_path, monkeypatch):
    def run_with(kind: str) -> list[tuple]:
        with provider(kind, tmp_path / kind, monkeypatch) as storage:
            app.dependency_overrides[get_storage] = lambda: storage
            try:
                client.cookies.clear()
                sign_up(client, f"{kind}-{uuid.uuid4().hex[:8]}@example.com")
                video_id, _ = stored_video(client, db_session, storage)
                results = observe(client, video_id)

                client.cookies.clear()
                sign_up(client, f"other-{uuid.uuid4().hex[:8]}@example.com")
                foreign = client.get(f"/videos/{video_id}/content").status_code
                results.append(("foreign", foreign))

                client.cookies.clear()
                return results
            finally:
                app.dependency_overrides.pop(get_storage, None)

    return run_with


def test_local_and_s3_serve_identical_responses(run):
    local, s3 = run("local"), run("s3-moto")

    assert local == s3
    by_header = {entry[0]: entry for entry in local if len(entry) == 4}
    assert by_header[None][1] == 200 and by_header[None][3] == CONTENT
    assert by_header["bytes=0-99"][1:3] == (
        206,
        {**by_header["bytes=0-99"][2], "content-range": "bytes 0-99/2560", "content-length": "100"},
    )
    assert by_header["bytes=-50"][3] == CONTENT[-50:]
    assert by_header["bytes=2560-"][1] == 416
    assert by_header["bytes=2560-"][2]["content-range"] == "bytes */2560"
    assert by_header["bytes=0-10,20-30"][1] == 200  # multiple ranges: everything
    assert by_header[None][2]["cache-control"] == "private, no-store"
    assert ("foreign", 404) in local


@pytest.mark.parametrize("kind", ["local", "s3-moto"])
def test_a_vanished_object_is_a_404(kind, client, db_session, tmp_path, monkeypatch):
    with provider(kind, tmp_path, monkeypatch) as storage:
        app.dependency_overrides[get_storage] = lambda: storage
        try:
            sign_up(client, "vanish@example.com")
            video_id, key = stored_video(client, db_session, storage)
            storage.delete(key)
            response = client.get(f"/videos/{video_id}/content")
        finally:
            app.dependency_overrides.pop(get_storage, None)
    assert response.status_code == 404
    assert key not in response.text


class BrokenStorage:
    backend = "s3"

    def generate_key(self, extension, category="videos"):
        return f"{category}/{uuid.uuid4().hex}.{extension}"

    def save(self, stream, key, *, max_bytes=None):
        return 1

    def __getattr__(self, name):
        def unavailable(*args, **kwargs):
            raise StorageUnavailable("Object storage request failed")

        return unavailable


def test_a_storage_outage_is_a_503_not_a_missing_file(client, db_session):
    storage = BrokenStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        sign_up(client, "outage@example.com")
        video_id, key = stored_video(client, db_session, storage)
        response = client.get(f"/videos/{video_id}/content", headers={"Range": "bytes=0-9"})
    finally:
        app.dependency_overrides.pop(get_storage, None)
    assert response.status_code == 503
    assert response.json() == {"detail": "Media storage is temporarily unavailable"}
    assert key not in response.text
