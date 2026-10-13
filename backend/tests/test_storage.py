import io
import os
from pathlib import Path

import pytest

from app.services.storage import (
    CHUNK_SIZE,
    FileTooLarge,
    InvalidStorageKey,
    LocalMediaStorage,
    StorageError,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalMediaStorage:
    return LocalMediaStorage(tmp_path / "media")


# --- keys -----


def test_generate_key_is_unique_uuid_based_and_lowercases_extension():
    first = LocalMediaStorage.generate_key("MP4")
    second = LocalMediaStorage.generate_key("mp4")

    assert first != second
    assert first.startswith("videos/") and first.endswith(".mp4")
    assert len(first) == len("videos/") + 32 + len(".mp4")


@pytest.mark.parametrize("extension", ["", "mp4/../../x", "m p4", "mp4;rm", "." * 3, "x" * 17])
def test_generate_key_rejects_unsafe_extensions(extension: str):
    with pytest.raises(InvalidStorageKey):
        LocalMediaStorage.generate_key(extension)


def test_generate_key_never_uses_the_original_filename():
    key = LocalMediaStorage.generate_key("mov")

    assert "stream" not in key  # keys carry no user-controlled text at all


@pytest.mark.parametrize(
    "key",
    [
        "../secret.mp4",
        "videos/../../etc/passwd",
        "/etc/passwd",
        "videos/..",
        "videos//x.mp4",
        "videos/x.mp4/",
        "videos\\x.mp4",
        "videos/x y.mp4",
        "videos/x.mp4\x00",
        "",
        "videos/..hidden",
    ],
)
def test_path_for_rejects_traversal_and_malformed_keys(storage: LocalMediaStorage, key: str):
    with pytest.raises(InvalidStorageKey):
        storage.path_for(key)


def test_path_for_stays_inside_root(storage: LocalMediaStorage):
    path = storage.path_for("videos/abc.mp4")

    assert path == storage.root / "videos" / "abc.mp4"
    assert storage.root in path.parents


def test_root_symlink_does_not_allow_escape(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "media"
    root.mkdir()
    (root / "videos").symlink_to(outside)
    storage = LocalMediaStorage(root)

    with pytest.raises(InvalidStorageKey):
        storage.path_for("videos/escaped.mp4")


# --- save / exists / delete -----


def test_save_writes_in_chunks_and_reports_size(storage: LocalMediaStorage):
    payload = os.urandom(CHUNK_SIZE * 2 + 123)

    written = storage.save(io.BytesIO(payload), "videos/a.mp4")

    assert written == len(payload)
    assert storage.exists("videos/a.mp4")
    assert storage.size("videos/a.mp4") == len(payload)
    assert storage.path_for("videos/a.mp4").read_bytes() == payload
    assert not list(storage.root.glob("**/.*.part"))


def test_save_enforces_limit_and_leaves_nothing_behind(storage: LocalMediaStorage):
    payload = os.urandom(CHUNK_SIZE + 1)

    with pytest.raises(FileTooLarge) as excinfo:
        storage.save(io.BytesIO(payload), "videos/big.mp4", max_bytes=CHUNK_SIZE)

    assert excinfo.value.limit == CHUNK_SIZE
    assert not storage.exists("videos/big.mp4")
    assert not [p for p in storage.root.rglob("*") if p.is_file()]  # no partial files either


def test_save_exactly_at_limit_is_allowed(storage: LocalMediaStorage):
    payload = b"x" * 10

    assert storage.save(io.BytesIO(payload), "videos/ok.mp4", max_bytes=10) == 10


def test_save_cleans_up_when_the_stream_fails(storage: LocalMediaStorage):
    class BrokenStream(io.RawIOBase):
        calls = 0

        def read(self, size: int = -1) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"partial data"
            raise OSError("connection dropped")

    with pytest.raises(OSError):
        storage.save(BrokenStream(), "videos/broken.mp4")  # type: ignore[arg-type]

    assert not storage.exists("videos/broken.mp4")
    assert not list(storage.root.glob("**/*.part"))


def test_save_refuses_to_overwrite(storage: LocalMediaStorage):
    storage.save(io.BytesIO(b"first"), "videos/dup.mp4")

    with pytest.raises(StorageError):
        storage.save(io.BytesIO(b"second"), "videos/dup.mp4")

    assert storage.path_for("videos/dup.mp4").read_bytes() == b"first"


def test_save_rejects_unsafe_key_before_touching_disk(storage: LocalMediaStorage):
    with pytest.raises(InvalidStorageKey):
        storage.save(io.BytesIO(b"data"), "../escape.mp4")

    assert not storage.root.exists()


def test_delete_removes_file_and_tolerates_missing(storage: LocalMediaStorage):
    storage.save(io.BytesIO(b"data"), "videos/gone.mp4")

    storage.delete("videos/gone.mp4")
    storage.delete("videos/gone.mp4")

    assert not storage.exists("videos/gone.mp4")
