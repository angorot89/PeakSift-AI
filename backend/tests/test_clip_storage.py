import uuid
from pathlib import Path

import pytest

from app.services.clip_render.storage import (
    ArtifactExists,
    ArtifactMissing,
    ClipArtifactStore,
    clip_storage_key,
    clip_temp_key,
    safe_download_filename,
)
from app.services.storage import InvalidStorageKey, LocalMediaStorage


@pytest.fixture
def store(tmp_path: Path) -> ClipArtifactStore:
    return ClipArtifactStore(LocalMediaStorage(tmp_path / "media"))


# --- keys ------------------------------------------------------------------------------------


def test_keys_are_generated_from_the_clip_id_only():
    clip_id = uuid.uuid4()
    assert clip_storage_key(clip_id) == f"clips/{clip_id}/clip.mp4"
    assert clip_temp_key(clip_id) == f"clips/{clip_id}/clip-tmp.mp4"
    assert clip_storage_key(str(clip_id)) == clip_storage_key(clip_id)


@pytest.mark.parametrize("bad", ["../etc", "x/../../y", "My Title", "", "clip.mp4", "..", "a" * 36])
def test_only_real_uuids_can_name_a_clip(bad):
    with pytest.raises(ValueError):
        clip_storage_key(bad)
    with pytest.raises(ValueError):
        clip_temp_key(bad)


def test_paths_stay_inside_the_media_root(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    for path in (store.temp_path(clip_id), store.final_path(clip_id)):
        assert store.storage.root in path.parents
        assert path.parent.name == str(clip_id) and path.parent.parent.name == "clips"


def test_storage_refuses_traversal_even_if_a_key_were_forged(store: ClipArtifactStore):
    with pytest.raises(InvalidStorageKey):
        store.storage.path_for("clips/../../../etc/passwd")


# --- temp → final ---------------------------------------------------------------------------


def test_temp_path_creates_the_directory_and_clears_stale_temp(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    first = store.temp_path(clip_id)
    first.write_bytes(b"half-written")
    second = store.temp_path(clip_id)
    assert second == first and not second.exists()  # stale temp from a crash is gone
    assert second.parent.is_dir()


def test_finalize_is_an_atomic_rename_and_removes_the_temp(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    temp = store.temp_path(clip_id)
    temp.write_bytes(b"\x00" * 1024)

    key = store.finalize(clip_id)

    assert key == clip_storage_key(clip_id)
    assert store.exists(clip_id)
    assert store.final_path(clip_id).read_bytes() == b"\x00" * 1024
    assert not temp.exists()


def test_finalize_refuses_missing_or_empty_output(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    with pytest.raises(ArtifactMissing):
        store.finalize(clip_id)
    store.temp_path(clip_id).write_bytes(b"")
    with pytest.raises(ArtifactMissing):
        store.finalize(clip_id)
    assert not store.exists(clip_id)


def test_finalize_never_overwrites_a_final_artifact(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    store.temp_path(clip_id).write_bytes(b"first")
    store.finalize(clip_id)
    store.temp_path(clip_id).write_bytes(b"second")
    with pytest.raises(ArtifactExists):
        store.finalize(clip_id)
    assert store.final_path(clip_id).read_bytes() == b"first"


def test_exists_requires_a_non_empty_final_file(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    assert not store.exists(clip_id)
    store.final_path(clip_id).parent.mkdir(parents=True)
    store.final_path(clip_id).write_bytes(b"")
    assert not store.exists(clip_id)


def test_discard_removes_everything_and_is_idempotent(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    store.temp_path(clip_id).write_bytes(b"partial")
    store.discard(clip_id)
    assert not store.final_path(clip_id).parent.exists()

    store.temp_path(clip_id).write_bytes(b"x")
    store.finalize(clip_id)
    store.discard(clip_id)
    assert not store.exists(clip_id) and not store.final_path(clip_id).parent.exists()
    store.discard(clip_id)  # nothing there: still fine


def test_discard_temp_keeps_a_final_artifact(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    store.temp_path(clip_id).write_bytes(b"x")
    store.finalize(clip_id)
    store.temp_path(clip_id).write_bytes(b"leftover")
    store.discard_temp(clip_id)
    assert store.exists(clip_id) and not store.storage.path_for(clip_temp_key(clip_id)).exists()


def test_two_clips_never_share_a_location(store: ClipArtifactStore):
    a, b = uuid.uuid4(), uuid.uuid4()
    assert store.final_path(a) != store.final_path(b)
    assert store.final_path(a).parent != store.final_path(b).parent


# --- download filename -----------------------------------------------------------------------


def test_download_filename_is_a_slug_plus_short_id():
    clip_id = uuid.UUID("3f2c9a1e-0000-4000-8000-000000000000")
    assert safe_download_filename("That Was Crazy!", clip_id) == "that-was-crazy-3f2c9a1e.mp4"


@pytest.mark.parametrize(
    ("title", "expected_prefix"),
    [
        ('../../etc/passwd "quoted" \x00\x1b', "etc-passwd-quoted-"),
        ("Été à Paris — café", "ete-a-paris-cafe-"),
        ("مرحبا بكم", "clip-"),  # no ASCII letters left → generic name
        ("", "clip-"),
        (None, "clip-"),
        ("x" * 500, "x" * 60 + "-"),
        ("   ---   ", "clip-"),
    ],
)
def test_download_filename_neutralises_unsafe_titles(title, expected_prefix):
    clip_id = uuid.uuid4()
    name = safe_download_filename(title, clip_id)
    assert name.startswith(expected_prefix) and name.endswith(f"{str(clip_id)[:8]}.mp4")
    assert "/" not in name and "\\" not in name and '"' not in name
    assert all(ch.isascii() and ch.isprintable() for ch in name)
    assert len(name) <= 60 + 1 + 8 + 4


def test_same_title_different_clips_get_different_names():
    assert safe_download_filename("Same", uuid.uuid4()) != safe_download_filename(
        "Same", uuid.uuid4()
    )
