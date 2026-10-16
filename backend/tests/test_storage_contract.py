"""The media storage contract, run unchanged against every provider.

``local`` and ``s3-moto`` always run; ``s3-live`` runs against a real S3-compatible service
when ``TEST_S3_*`` is configured (see ``storage_backends``).
"""

import io
import os
from pathlib import Path

import httpx
import pytest

from app.services.storage import (
    CHUNK_SIZE,
    FileTooLarge,
    InvalidStorageKey,
    ObjectExists,
    ObjectNotFound,
    S3StorageProvider,
    StorageUnavailable,
)
from tests.storage_backends import BACKENDS, live_available, provider

DATA = bytes(range(256)) * 40  # 10 KiB of distinguishable bytes


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path, monkeypatch):
    if request.param == "s3-live" and not live_available():
        pytest.skip("TEST_S3_ENDPOINT_URL / credentials are not set")
    with provider(request.param, tmp_path, monkeypatch) as store:
        yield store


def read(storage, key: str, start: int, end: int) -> bytes:
    return b"".join(storage.iter_range(key, start, end))


# --- write, read, size -----


def test_saved_object_reads_back_whole_and_by_range(storage):
    key = storage.generate_key("mp4")
    assert storage.save(io.BytesIO(DATA), key) == len(DATA)

    assert storage.exists(key)
    assert storage.size(key) == len(DATA)
    assert read(storage, key, 0, len(DATA) - 1) == DATA
    assert read(storage, key, 100, 199) == DATA[100:200]
    assert read(storage, key, len(DATA) - 50, len(DATA) - 1) == DATA[-50:]  # a suffix range
    assert read(storage, key, 7, 7) == DATA[7:8]


def test_large_objects_stream_in_bounded_chunks(storage):
    data = os.urandom(CHUNK_SIZE * 2 + 123)
    key = storage.generate_key("mp4")
    storage.save(io.BytesIO(data), key)

    chunks = list(storage.iter_range(key, 0, len(data) - 1))
    assert len(chunks) >= 3 and max(len(chunk) for chunk in chunks) <= CHUNK_SIZE
    assert b"".join(chunks) == data
    assert (
        read(storage, key, CHUNK_SIZE - 10, CHUNK_SIZE + 10)
        == data[CHUNK_SIZE - 10 : CHUNK_SIZE + 11]
    )


def test_keys_are_never_overwritten(storage):
    key = storage.generate_key("mp3")
    storage.save(io.BytesIO(b"first"), key)

    with pytest.raises(ObjectExists):
        storage.save(io.BytesIO(b"second"), key)
    assert read(storage, key, 0, 4) == b"first"


def test_an_oversized_stream_is_refused_and_leaves_nothing(storage):
    key = storage.generate_key("mp4")
    with pytest.raises(FileTooLarge):
        storage.save(io.BytesIO(DATA), key, max_bytes=len(DATA) - 1)
    assert not storage.exists(key)


def test_local_files_go_in_and_come_back_out(storage, tmp_path: Path):
    source = tmp_path / "render.mp4"
    source.write_bytes(DATA)
    key = storage.generate_key("mp4", category="edits")

    assert storage.put_file(source, key) == len(DATA)
    destination = tmp_path / "workspace" / "input.mp4"
    destination.parent.mkdir()
    assert storage.download_file(key, destination) == len(DATA)
    assert destination.read_bytes() == DATA
    assert [p.name for p in destination.parent.iterdir()] == ["input.mp4"]  # no partials


# --- missing objects -----


def test_missing_objects_are_reported_as_missing(storage, tmp_path: Path):
    key = storage.generate_key("mp4")

    assert storage.exists(key) is False
    with pytest.raises(ObjectNotFound):
        storage.size(key)
    with pytest.raises(ObjectNotFound):
        storage.iter_range(key, 0, 10)
    destination = tmp_path / "missing.mp4"
    with pytest.raises(ObjectNotFound):
        storage.download_file(key, destination)
    assert not destination.exists()
    assert not destination.with_name(".missing.mp4.part").exists()


def test_delete_is_idempotent(storage):
    key = storage.generate_key("wav", category="audio")
    storage.save(io.BytesIO(b"abc"), key)

    storage.delete(key)
    storage.delete(key)
    assert not storage.exists(key)


def test_health_check_passes(storage):
    storage.check()


# --- keys -----


@pytest.mark.parametrize(
    "key", ["", "../escape.mp4", "videos/../../etc/passwd", "/abs/path.mp4", "a//b.mp4", "a b"]
)
def test_unsafe_keys_are_refused_by_every_operation(storage, key, tmp_path: Path):
    for call in (
        lambda: storage.exists(key),
        lambda: storage.size(key),
        lambda: storage.save(io.BytesIO(b"x"), key),
        lambda: storage.put_file(tmp_path / "unused", key),
        lambda: storage.download_file(key, tmp_path / "out"),
        lambda: storage.iter_range(key, 0, 1),
        lambda: storage.delete(key),
    ):
        with pytest.raises(InvalidStorageKey):
            call()


# --- S3 specifics -----


@pytest.fixture
def s3(storage):
    if not isinstance(storage, S3StorageProvider):
        pytest.skip("S3 only")
    return storage


def test_objects_are_private_and_typed(s3):
    key = s3.generate_key("mp4", category="edits")
    s3.save(io.BytesIO(DATA), key)

    head = s3._client.head_object(Bucket=s3.bucket, Key=key)
    assert head["ContentType"] == "video/mp4"
    grants = s3._client.get_object_acl(Bucket=s3.bucket, Key=key)["Grants"]
    public = [g for g in grants if "URI" in g.get("Grantee", {})]  # AllUsers / AuthUsers
    assert public == []


def test_a_missing_bucket_makes_storage_unavailable_not_missing(s3):
    gone = S3StorageProvider(s3._client, "peaksift-no-such-bucket-0000")
    with pytest.raises(StorageUnavailable):
        gone.check()
    # A HEAD on a missing bucket is a bare 404, exactly like a missing object: it must
    # still be reported as broken storage, never as a missing artifact.
    for call in (
        lambda: gone.exists("videos/abc.mp4"),
        lambda: gone.size("videos/abc.mp4"),
        lambda: gone.iter_range("videos/abc.mp4", 0, 1),
    ):
        with pytest.raises(StorageUnavailable):
            call()


def test_anonymous_requests_cannot_read_objects(s3):
    endpoint = os.environ.get("TEST_S3_ENDPOINT_URL")
    if not endpoint or s3.bucket == "peaksift-contract":
        pytest.skip("needs the live service")
    key = s3.generate_key("mp4")
    s3.save(io.BytesIO(DATA), key)

    response = httpx.get(f"{endpoint}/{s3.bucket}/{key}", timeout=5)
    assert response.status_code == 403
    assert DATA[:64] not in response.content


def test_an_unreachable_endpoint_is_unavailable_and_says_nothing_secret():
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:9",
        region_name="us-east-1",
        aws_access_key_id="AKIAEXAMPLEKEY",
        aws_secret_access_key="super-secret-value",
        config=Config(connect_timeout=0.5, retries={"max_attempts": 1}),
    )
    storage = S3StorageProvider(client, "peaksift-media")
    for call in (storage.check, lambda: storage.exists("videos/secret-name.mp4")):
        with pytest.raises(StorageUnavailable) as excinfo:
            call()
        message = str(excinfo.value)
        assert "secret" not in message and "AKIA" not in message and "127.0.0.1" not in message


def test_storage_errors_never_carry_the_key(storage):
    key = storage.generate_key("mp4")
    with pytest.raises(ObjectNotFound) as excinfo:
        storage.size(key)
    assert key not in str(excinfo.value)
    with pytest.raises(InvalidStorageKey) as excinfo:
        storage.size("../private/thing.mp4")
    assert "private" not in str(excinfo.value)
