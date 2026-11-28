"""PeakSift's built-in starter library: sound effects, music beds and stickers.

Every item is openly licensed for redistribution inside PeakSift *and* for use in creators'
published (commercial) videos, with no credit they must add: CC0 (Kenney, OpenGameArt.org
authors) or MIT (Microsoft Fluent Emoji; its notice ships with the library and is shown in the
editor's credits). The catalogue is ``library_manifest.json`` (committed: titles, licences,
sources, sha256); the files are a release archive installed by an operator with
``scripts/fetch_library.py`` into ``LIBRARY_DIR`` — never committed, never fetched by the app.
A file is served or imported only when it matches its pinned sha256.

Using an item imports it into the project as an ordinary audio or visual asset, through the very
same validation as an upload (probing, limits, re-encoding, de-duplication), labelled with where
it comes from (CC0, or licensed with the licence written down). Everything after that — the
editor, the render, ownership checks — is unchanged.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.core.config import Settings
from app.models import AudioAsset, AudioAssetKind, Project, VisualAsset
from app.services import asset_labels
from app.services.audio_assets import store_audio_upload
from app.services.storage import StorageProvider
from app.services.visual_assets import store_visual_upload

MANIFEST_PATH = Path(__file__).with_name("library_manifest.json")
KINDS = ("sfx", "music", "sticker")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_FILE = re.compile(r"^(sfx|music|stickers)/[a-z0-9][a-z0-9-]{0,79}\.(ogg|png)$")
CONTENT_TYPES = {".ogg": "audio/ogg", ".png": "image/png"}


@dataclass(frozen=True)
class LibraryItem:
    id: str
    kind: str
    title: str
    category: str
    tags: tuple[str, ...]
    file: str
    sha256: str
    bytes: int
    licence: str
    source_name: str
    source_url: str
    credit: str
    duration_seconds: float | None = None

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES[Path(self.file).suffix]


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def items() -> tuple[LibraryItem, ...]:
    """The catalogue, validated (an item that breaks the rules is a build error, not data)."""
    out: list[LibraryItem] = []
    seen: set[str] = set()
    for raw in manifest()["items"]:
        item = LibraryItem(
            id=raw["id"],
            kind=raw["kind"],
            title=raw["title"],
            category=raw["category"],
            tags=tuple(raw.get("tags", ())),
            file=raw["file"],
            sha256=raw["sha256"],
            bytes=int(raw["bytes"]),
            licence=raw["licence"],
            source_name=raw["source"]["name"],
            source_url=raw["source"]["url"],
            credit=raw["credit"],
            duration_seconds=raw.get("duration_seconds"),
        )
        if (
            not _ID.fullmatch(item.id)
            or item.id in seen
            or item.kind not in KINDS
            or not _FILE.fullmatch(item.file)
            or not re.fullmatch(r"[0-9a-f]{64}", item.sha256)
            or item.licence not in ("CC0-1.0", "MIT")
        ):
            raise ValueError(f"Invalid library item: {item.id!r}")
        seen.add(item.id)
        out.append(item)
    return tuple(out)


def find(item_id: str) -> LibraryItem | None:
    return next((item for item in items() if item.id == item_id), None)


@lru_cache(maxsize=512)
def _verified(path: str, size: int, mtime: float, sha256: str) -> bool:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha256


def item_file(item: LibraryItem, library_dir: str | Path) -> Path | None:
    """The installed, verified file of an item; None when missing or not the pinned file."""
    path = Path(library_dir) / item.file
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file() or not _verified(str(path), stat.st_size, stat.st_mtime, item.sha256):
        return None
    return path


def installed(library_dir: str | Path) -> bool:
    """Whether this server has the library (its manifest version is installed)."""
    marker = Path(library_dir) / "manifest.json"
    try:
        return (
            json.loads(marker.read_text(encoding="utf-8")).get("version") == manifest()["version"]
        )
    except (OSError, ValueError):
        return False


def labels_for(item: LibraryItem) -> dict:
    """Where an imported item comes from, as the creator's asset labels record it."""
    if item.licence == "CC0-1.0":
        return {"origin": "cc0", "license_note": item.credit}
    return {"origin": "licensed", "license_note": item.credit}


class LibraryItemUnavailable(Exception):
    """The item's file is not installed on this server (or does not match its pin)."""


def import_into(
    db: Session,
    storage: StorageProvider,
    project: Project,
    item: LibraryItem,
    settings: Settings,
) -> tuple[AudioAsset | VisualAsset, bool]:
    """Add the item to the project's assets (as an upload would be). The same item again
    returns the project's existing asset. Raises ``LibraryItemUnavailable`` or the upload's own
    ``UploadValidationError``."""
    path = item_file(item, settings.library_dir)
    if path is None:
        raise LibraryItemUnavailable(item.id)
    name = f"{item.title}{path.suffix}"
    with path.open("rb") as handle:
        upload = UploadFile(
            file=handle, filename=name, headers=Headers({"content-type": item.content_type})
        )
        if item.kind == "sticker":
            asset, created = store_visual_upload(db, storage, project, upload, settings)
            family = "visual"
        else:
            kind = AudioAssetKind.MUSIC if item.kind == "music" else AudioAssetKind.SFX
            asset, created = store_audio_upload(db, storage, project, upload, kind, settings)
            family = "audio"
    if created:
        for field, value in asset_labels.clean_labels(
            family, asset_labels.read(asset), labels_for(item)
        ).items():
            setattr(asset, field, value)
        db.commit()
    return asset, created
