import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Video
from app.services.video_upload import check_declared_size, sanitize_filename

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048  # looks like an MP4 header


def sign_up(client: TestClient, email: str) -> dict:
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return response.json()


def create_project(client: TestClient, name: str = "Stream") -> dict:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def upload(
    client: TestClient,
    project_id: str,
    filename: str = "stream.mp4",
    content: bytes = MP4_BYTES,
    content_type: str | None = "video/mp4",
):
    file = (filename, content, content_type) if content_type is not None else (filename, content)
    return client.post(f"/projects/{project_id}/videos", files={"file": file})


def media_root() -> Path:
    return Path(get_settings().media_root)


def stored_files() -> list[Path]:
    return [p for p in media_root().rglob("*") if p.is_file()]


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in stored_files():
        path.unlink()


# --- authentication and ownership ---------------------------------------------


def test_upload_requires_authentication(client: TestClient):
    response = upload(client, str(uuid.uuid4()))

    assert response.status_code == 401


def test_upload_to_other_users_project_is_not_found(client: TestClient):
    sign_up(client, "alice@example.com")
    alices_project = create_project(client)
    client.cookies.clear()
    sign_up(client, "bob@example.com")

    response = upload(client, alices_project["id"])

    assert response.status_code == 404
    assert stored_files() == []


def test_upload_to_unknown_project_is_not_found(client: TestClient):
    sign_up(client, "owner@example.com")

    assert upload(client, str(uuid.uuid4())).status_code == 404


# --- happy path -----------------------------------------------------------------


def test_upload_valid_mp4(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["project_id"] == project["id"]
    assert body["original_filename"] == "stream.mp4"
    assert body["content_type"] == "video/mp4"
    assert body["file_size"] == len(MP4_BYTES)
    # Metadata probing runs synchronously; these bytes are not real media, so it fails.
    assert body["status"] in ("ready", "failed")
    assert uuid.UUID(body["id"])
    assert body["created_at"]
    # Nothing about where the file lives leaks out.
    assert "storage_key" not in body
    assert str(media_root()) not in response.text

    video = db_session.scalar(select(Video).where(Video.id == uuid.UUID(body["id"])))
    assert video is not None
    assert re.fullmatch(r"videos/[0-9a-f]{32}\.mp4", video.storage_key)
    assert "stream" not in video.storage_key
    assert (media_root() / video.storage_key).read_bytes() == MP4_BYTES


@pytest.mark.parametrize(
    ("filename", "sent_type", "stored_type"),
    [
        ("clip.mov", "video/quicktime", "video/quicktime"),
        ("clip.webm", "video/webm", "video/webm"),
        ("CLIP.MP4", "video/mp4", "video/mp4"),
        ("clip.mp4", "application/octet-stream", "video/mp4"),
        ("clip.mov", None, "video/quicktime"),
    ],
)
def test_supported_formats_and_generic_content_types(
    client: TestClient, filename: str, sent_type: str | None, stored_type: str
):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"], filename=filename, content_type=sent_type)

    assert response.status_code == 201, response.text
    assert response.json()["content_type"] == stored_type
    assert response.json()["original_filename"] == filename


def test_each_upload_gets_a_unique_storage_key(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    upload(client, project["id"])
    upload(client, project["id"])

    keys = list(db_session.scalars(select(Video.storage_key)))
    assert len(keys) == 2 and len(set(keys)) == 2
    assert len(stored_files()) == 2


# --- validation -------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["movie.avi", "notes.txt", "noextension", "clip.mp4.exe"])
def test_unsupported_extension_is_rejected(client: TestClient, filename: str):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"], filename=filename, content_type=None)

    assert response.status_code == 415
    assert stored_files() == []


def test_content_type_must_match_extension(client: TestClient):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"], filename="clip.mp4", content_type="video/webm")

    assert response.status_code == 415
    assert stored_files() == []


def test_oversized_upload_is_rejected_and_cleaned_up(client: TestClient, monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "max_video_upload_bytes", 1024)
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"], content=b"x" * 1025)

    assert response.status_code == 413
    assert "1024" not in response.json()["detail"] or "MB" in response.json()["detail"]
    assert stored_files() == []
    assert db_session.scalar(select(Video)) is None


def test_upload_at_exact_limit_succeeds(client: TestClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_video_upload_bytes", 1024)
    sign_up(client, "owner@example.com")
    project = create_project(client)

    assert upload(client, project["id"], content=b"x" * 1024).status_code == 201


def test_zero_byte_upload_is_rejected(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"], content=b"")

    assert response.status_code == 400
    assert stored_files() == []
    assert db_session.scalar(select(Video)) is None


def test_missing_file_field_is_a_validation_error(client: TestClient):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    assert client.post(f"/projects/{project['id']}/videos", data={"x": "y"}).status_code == 422


# --- filenames ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        ("../../etc/passwd.mp4", "passwd.mp4"),
        ("..\\..\\Windows\\evil.mp4", "evil.mp4"),
        ("/absolute/path/clip.mp4", "clip.mp4"),
        ("  spaced name .mp4  ", "spaced name .mp4"),
        ("clip été 🎬.mp4", "clip été 🎬.mp4"),
        ("weird<>|?*.mp4", "weird.mp4"),
    ],
)
def test_filenames_are_sanitized_but_preserved_as_metadata(
    client: TestClient, db_session: Session, sent: str, expected: str
):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"], filename=sent)

    assert response.status_code == 201, response.text
    assert response.json()["original_filename"] == expected
    stored = stored_files()
    assert len(stored) == 1
    assert media_root().resolve() in stored[0].resolve().parents
    assert stored[0].name != expected


def test_long_filename_is_truncated_keeping_extension(client: TestClient):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    response = upload(client, project["id"], filename="a" * 300 + ".mp4")

    assert response.status_code == 201
    name = response.json()["original_filename"]
    assert len(name) == 255 and name.endswith(".mp4")


def test_sanitize_filename_edge_cases():
    # (httpx percent-encodes NUL and quotes in multipart names, so these are unit-tested.)
    assert sanitize_filename("clip\x00\x07.mp4") == "clip.mp4"
    assert sanitize_filename('weird<>:"|?*.mp4') == "weird.mp4"
    assert sanitize_filename("tab\there.mov") == "tabhere.mov"
    assert sanitize_filename(None) == "video"
    assert sanitize_filename("...") == "video"
    assert sanitize_filename("dir/") == "video"
    assert sanitize_filename("a/b/c.webm") == "c.webm"


# --- cleanup after failure ----------------------------------------------------------


def test_database_failure_removes_stored_file(client: TestClient, db_session: Session, monkeypatch):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    def failing_commit() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db_session, "commit", failing_commit)
    response = upload(client, project["id"])

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "database unavailable" not in response.text
    assert stored_files() == []
    monkeypatch.undo()
    db_session.rollback()
    assert db_session.scalar(select(Video)) is None


# --- declared size pre-check ----------------------------------------------------------


def test_check_declared_size():
    check_declared_size(None, 100)
    check_declared_size("not-a-number", 100)
    check_declared_size(str(100 + 64 * 1024), 100)  # within multipart slack
    with pytest.raises(Exception) as excinfo:
        check_declared_size(str(100 + 64 * 1024 + 1), 100)
    assert excinfo.value.status_code == 413


# --- reliability: interrupted / chunked bodies, resource cleanup -------------------

BOUNDARY = "testboundary"
MULTIPART_TYPE = f"multipart/form-data; boundary={BOUNDARY}"
PART_HEAD = (
    f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="clip.mp4"\r\n'
    "Content-Type: video/mp4\r\n\r\n"
).encode()
PART_TAIL = f"\r\n--{BOUNDARY}--\r\n".encode()


def test_truncated_multipart_body_stores_nothing(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    project = create_project(client)
    body = PART_HEAD + b"x" * 4096 + PART_TAIL

    response = client.post(
        f"/projects/{project['id']}/videos",
        content=body[: len(body) // 2],  # connection dropped halfway
        headers={"Content-Type": MULTIPART_TYPE},
    )

    assert 400 <= response.status_code < 500
    assert stored_files() == []
    assert db_session.scalar(select(Video)) is None


def test_chunked_upload_without_content_length_is_still_limited(client, monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "max_video_upload_bytes", 4096)
    sign_up(client, "owner@example.com")
    project = create_project(client)

    def body():
        yield PART_HEAD
        yield b"y" * 4097
        yield PART_TAIL

    response = client.post(
        f"/projects/{project['id']}/videos",
        content=body(),
        headers={"Content-Type": MULTIPART_TYPE, "Transfer-Encoding": "chunked"},
    )

    assert response.status_code == 413
    assert stored_files() == []
    assert db_session.scalar(select(Video)) is None


def test_extension_only_filename_is_unsupported(client: TestClient):
    sign_up(client, "owner@example.com")
    project = create_project(client)

    assert upload(client, project["id"], filename=".mp4").status_code == 415
    assert stored_files() == []


def test_repeated_uploads_do_not_leak_file_descriptors(client: TestClient):
    sign_up(client, "owner@example.com")
    project = create_project(client)
    fd_dir = Path("/dev/fd")
    if not fd_dir.exists():
        pytest.skip("/dev/fd not available")
    upload(client, project["id"])  # warm up pools and caches
    before = len(list(fd_dir.iterdir()))

    for _ in range(20):
        assert upload(client, project["id"]).status_code == 201

    after = len(list(fd_dir.iterdir()))
    assert after - before <= 3, f"file descriptors grew from {before} to {after}"
    assert not [p for p in stored_files() if p.name.endswith(".part")]
