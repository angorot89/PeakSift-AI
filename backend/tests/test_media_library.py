"""The built-in starter library: catalogue, installation, browsing and adding items to projects.

The real catalogue is checked as data; everything that touches files uses a small library
generated here (FFmpeg tones, a Pillow image) so no test downloads anything.
"""

import hashlib
import io
import json
import tarfile
import uuid
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import get_settings
from app.services import library
from tests.test_audio_assets_api import audio_files, make_audio
from tests.test_audio_assets_api import clean_media_root as _clean  # noqa: F401
from tests.test_projects import create_project, sign_up

clean_media_root = _clean


# --- the real catalogue ----------------------------------------------------------------------


def test_the_catalogue_is_complete_and_openly_licensed():
    items = library.items()
    kinds = {kind: [i for i in items if i.kind == kind] for kind in library.KINDS}
    assert len(kinds["sfx"]) >= 60 and len(kinds["music"]) >= 10 and len(kinds["sticker"]) >= 30
    assert {i.licence for i in items} <= {"CC0-1.0", "MIT"}
    assert all(i.licence == "MIT" for i in kinds["sticker"])  # Fluent Emoji
    assert all(i.source_url.startswith("https://") and i.credit for i in items)
    assert len({i.id for i in items}) == len(items)
    assert all(i.duration_seconds and i.duration_seconds <= 30 for i in kinds["sfx"])
    assert all(i.duration_seconds and i.duration_seconds <= 180.5 for i in kinds["music"])


def test_imported_items_say_where_they_come_from():
    cc0 = next(i for i in library.items() if i.licence == "CC0-1.0")
    mit = next(i for i in library.items() if i.licence == "MIT")
    assert library.labels_for(cc0) == {"origin": "cc0", "license_note": cc0.credit}
    assert library.labels_for(mit)["origin"] == "licensed" and "MIT" in mit.credit


# --- a generated library -----------------------------------------------------------------------


def build_library(root: Path) -> dict:
    """A tiny installed library (one sound, one track, one sticker) and its manifest."""
    (root / "sfx").mkdir(parents=True)
    (root / "music").mkdir()
    (root / "stickers").mkdir()
    (root / "licences").mkdir()
    make_audio(root / "sfx" / "pop-1.ogg", seconds=0.6)
    make_audio(root / "music" / "calm-bed.ogg", seconds=4.0, freq=220)
    Image.new("RGBA", (64, 64), (255, 80, 0, 200)).save(root / "stickers" / "fire.png")
    (root / "licences" / "kenney-CC0.txt").write_text("CC0", encoding="utf-8")

    def entry(kind, file, title, licence, credit, seconds=None):
        path = root / file
        data = {
            "id": path.stem, "kind": kind, "title": title, "category": "test", "tags": [],
            "file": file, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size, "licence": licence,
            "source": {"name": "Kenney", "url": "https://kenney.nl"}, "credit": credit,
        }  # fmt: skip
        if seconds:
            data["duration_seconds"] = seconds
        return data

    manifest = {
        "version": "library-test",
        "items": [
            entry("sfx", "sfx/pop-1.ogg", "Pop 1", "CC0-1.0", "Kenney (kenney.nl), CC0", 0.6),
            entry("music", "music/calm-bed.ogg", "Calm bed", "CC0-1.0", "Someone, CC0", 4.0),
            entry("sticker", "stickers/fire.png", "Fire", "MIT", "Fluent Emoji, MIT licence"),
        ],
        "licences": ["licences/kenney-CC0.txt"],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "library"
    manifest = build_library(root)
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(library, "MANIFEST_PATH", catalogue)
    monkeypatch.setenv("LIBRARY_DIR", str(root))
    library.manifest.cache_clear()
    library.items.cache_clear()
    get_settings.cache_clear()
    yield root
    library.manifest.cache_clear()
    library.items.cache_clear()
    get_settings.cache_clear()


def test_a_file_that_differs_from_its_pin_is_never_used(installed):
    item = library.find("pop-1")
    assert library.item_file(item, installed) is not None
    (installed / "sfx" / "pop-1.ogg").write_bytes(b"tampered")
    assert library.item_file(item, installed) is None


def test_the_installer_verifies_and_extracts_only_listed_files(installed, tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fetch_library", Path(__file__).parents[1] / "scripts" / "fetch_library.py"
    )
    fetch_library = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch_library)

    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(installed, arcname="library-test")
        evil = tarfile.TarInfo("library-test/../../escape.txt")
        payload = b"nope"
        evil.size = len(payload)
        tar.addfile(evil, io.BytesIO(payload))
    target = tmp_path / "out" / "library"
    target.parent.mkdir()
    monkeypatch.setattr(fetch_library, "RELEASE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="pinned sha256"):
        fetch_library.install(archive, target)
    monkeypatch.setattr(
        fetch_library, "RELEASE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    assert fetch_library.install(archive, target) == 3
    assert library.installed(target) and not (tmp_path / "escape.txt").exists()
    assert sorted(p.name for p in (target / "sfx").iterdir()) == ["pop-1.ogg"]


# --- the API -----------------------------------------------------------------------------------


@pytest.fixture
def project(client):
    sign_up(client, f"lib-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client, "Library")["id"]


def test_browsing_needs_no_installation_and_leaks_no_paths(client, project, tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARY_DIR", str(tmp_path / "nothing"))
    get_settings.cache_clear()
    try:
        data = client.get("/library").json()
    finally:
        get_settings.cache_clear()
    assert data["available"] is False and len(data["items"]) == len(library.items())
    assert {s["name"] for s in data["sources"]} >= {"Kenney", "Microsoft Fluent Emoji"}
    for leak in ("sha256", "library/", ".ogg", ".png", "file"):
        assert leak not in json.dumps(data["items"][0])


def test_items_play_only_when_installed(client, project, installed):
    response = client.get("/library/pop-1/content")
    assert response.status_code == 200 and response.headers["content-type"] == "audio/ogg"
    assert client.get("/library/fire/content").headers["content-type"] == "image/png"
    assert client.get("/library/not-an-item/content").status_code == 404
    assert client.get("/library/..%2Fmanifest/content").status_code == 404
    client.cookies.clear()
    assert client.get("/library/pop-1/content").status_code == 401


def test_adding_items_imports_them_as_labelled_project_assets(client, project, installed):
    added = client.post(f"/projects/{project}/library/pop-1")
    assert added.status_code == 201, added.text
    sound = added.json()["audio_asset"]
    assert added.json()["kind"] == "audio" and sound["kind"] == "sfx"
    assert sound["origin"] == "cc0" and "Kenney" in sound["license_note"]
    again = client.post(f"/projects/{project}/library/pop-1")
    assert again.status_code == 200 and again.json()["audio_asset"]["id"] == sound["id"]

    music = client.post(f"/projects/{project}/library/calm-bed").json()["audio_asset"]
    assert music["kind"] == "music" and music["duration_seconds"] == pytest.approx(4.0, abs=0.1)

    sticker = client.post(f"/projects/{project}/library/fire")
    assert sticker.status_code == 201, sticker.text
    visual = sticker.json()["visual_asset"]
    assert visual["kind"] == "image" and visual["has_alpha"] is True
    assert visual["origin"] == "licensed" and "MIT" in visual["license_note"]
    listed = client.get(f"/projects/{project}/audio-assets").json()
    assert {a["id"] for a in listed} == {sound["id"], music["id"]}
    assert audio_files()  # stored through the normal media storage


def test_adding_is_owner_scoped_and_needs_the_library(client, project, installed, monkeypatch):
    sign_up(client, f"other-{uuid.uuid4().hex[:8]}@example.com")
    assert client.post(f"/projects/{project}/library/pop-1").status_code == 404
    mine = create_project(client, "Mine")["id"]
    assert client.post(f"/projects/{mine}/library/nope").status_code == 404
    (installed / "sfx" / "pop-1.ogg").unlink()
    response = client.post(f"/projects/{mine}/library/pop-1")
    assert response.status_code == 409 and "/" not in response.json()["detail"]
