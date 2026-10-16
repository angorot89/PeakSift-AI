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
from app.services.storage import InvalidStorageKey, LocalStorageProvider


@pytest.fixture
def store(tmp_path: Path) -> ClipArtifactStore:
    return ClipArtifactStore(
        LocalStorageProvider(tmp_path / "media"), LocalStorageProvider(tmp_path / "work")
    )


def final(store: ClipArtifactStore, clip_id) -> Path:
    """The final artifact's file (these tests use the local provider)."""
    return store.storage.path_for(clip_storage_key(clip_id))


def clip_dirs(store: ClipArtifactStore, clip_id) -> list[Path]:
    """The clip's directories in media storage and in scratch."""
    return [root / "clips" / str(clip_id) for root in (store.storage.root, store.scratch.root)]


# --- keys -----


def test_keys_are_generated_from_the_clip_id_only():
    clip_id = uuid.uuid4()
    assert clip_storage_key(clip_id) == f"clips/{clip_id}/clip.mp4"
    assert clip_temp_key(clip_id) == f"clips/{clip_id}/clip-tmp-1.mp4"
    assert clip_temp_key(clip_id, 3) == f"clips/{clip_id}/clip-tmp-3.mp4"
    assert clip_storage_key(str(clip_id)) == clip_storage_key(clip_id)


@pytest.mark.parametrize("bad", ["../etc", "x/../../y", "My Title", "", "clip.mp4", "..", "a" * 36])
def test_only_real_uuids_can_name_a_clip(bad):
    with pytest.raises(ValueError):
        clip_storage_key(bad)
    with pytest.raises(ValueError):
        clip_temp_key(bad)


def test_temp_files_live_in_scratch_and_finals_in_media_storage(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    temp, done = store.temp_path(clip_id), final(store, clip_id)
    assert store.scratch.root in temp.parents and store.storage.root not in temp.parents
    assert store.storage.root in done.parents
    for path in (temp, done):
        assert path.parent.name == str(clip_id) and path.parent.parent.name == "clips"


def test_storage_refuses_traversal_even_if_a_key_were_forged(store: ClipArtifactStore):
    with pytest.raises(InvalidStorageKey):
        store.storage.path_for("clips/../../../etc/passwd")


# --- temp → final -----


def test_temp_path_creates_the_directory_and_clears_stale_temp(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    first = store.temp_path(clip_id)
    first.write_bytes(b"half-written")
    second = store.temp_path(clip_id)
    assert second == first and not second.exists()  # stale temp from a crash is gone
    assert second.parent.is_dir()


def test_finalize_stores_the_temp_file_and_removes_it(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    temp = store.temp_path(clip_id)
    temp.write_bytes(b"\x00" * 1024)

    key = store.finalize(clip_id)

    assert key == clip_storage_key(clip_id)
    assert store.exists(clip_id)
    assert final(store, clip_id).read_bytes() == b"\x00" * 1024
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
    assert final(store, clip_id).read_bytes() == b"first"


def test_exists_requires_a_non_empty_final_file(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    assert not store.exists(clip_id)
    final(store, clip_id).parent.mkdir(parents=True)
    final(store, clip_id).write_bytes(b"")
    assert not store.exists(clip_id)


def test_discard_removes_everything_and_is_idempotent(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    store.temp_path(clip_id).write_bytes(b"partial")
    store.discard(clip_id)
    assert not any(d.exists() for d in clip_dirs(store, clip_id))

    store.temp_path(clip_id).write_bytes(b"x")
    store.finalize(clip_id)
    store.discard(clip_id)
    assert not store.exists(clip_id) and not any(d.exists() for d in clip_dirs(store, clip_id))
    store.discard(clip_id)  # nothing there: still fine


def test_discard_temp_keeps_a_final_artifact(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    store.temp_path(clip_id).write_bytes(b"x")
    store.finalize(clip_id)
    store.temp_path(clip_id).write_bytes(b"leftover")
    store.discard_temp(clip_id)
    assert store.exists(clip_id) and not store.scratch.path_for(clip_temp_key(clip_id)).exists()


def test_two_clips_never_share_a_location(store: ClipArtifactStore):
    a, b = uuid.uuid4(), uuid.uuid4()
    assert final(store, a) != final(store, b)
    assert final(store, a).parent != final(store, b).parent
    assert store.temp_path(a).parent != store.temp_path(b).parent


# --- download filename -----


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


@pytest.mark.parametrize("attempt", [0, -1, True, 1.5, "2"])
def test_temp_keys_need_a_positive_integer_attempt(attempt):
    with pytest.raises(ValueError):
        clip_temp_key(uuid.uuid4(), attempt)


def test_each_attempt_has_its_own_temp_file(store: ClipArtifactStore):
    """A fenced-out attempt can neither overwrite nor clean up the new attempt's output."""
    clip_id = uuid.uuid4()
    old, new = store.temp_path(clip_id, 1), store.temp_path(clip_id, 2)
    assert old != new
    old.write_bytes(b"zombie")
    new.write_bytes(b"fresh")

    store.discard_temp(clip_id, 1)  # the zombie cleans up after itself...
    assert not old.exists() and new.read_bytes() == b"fresh"  # ...without touching attempt 2

    store.finalize(clip_id, 2)
    assert final(store, clip_id).read_bytes() == b"fresh"


def test_discard_removes_temp_files_of_every_attempt(store: ClipArtifactStore):
    clip_id = uuid.uuid4()
    for attempt in (1, 2, 3):
        store.temp_path(clip_id, attempt).write_bytes(b"x")
    store.discard(clip_id)
    assert not any(d.exists() for d in clip_dirs(store, clip_id))


def test_symlinked_clip_directory_cannot_escape_the_root(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "clip.mp4").write_bytes(b"secret")
    store = ClipArtifactStore(
        LocalStorageProvider(tmp_path / "media"), LocalStorageProvider(tmp_path / "work")
    )
    clip_id = uuid.uuid4()
    for root in (store.storage.root, store.scratch.root):
        (root / "clips").mkdir(parents=True)
        (root / "clips" / str(clip_id)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(InvalidStorageKey):
        store.exists(clip_id)
    with pytest.raises(InvalidStorageKey):
        store.temp_path(clip_id)
    assert (outside / "clip.mp4").read_bytes() == b"secret"
