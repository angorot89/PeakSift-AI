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

from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.core.config import Settings
from app.models import AudioAsset, AudioAssetKind, Project, VisualAsset
from app.services import asset_labels
from app.services.audio_assets import store_audio_upload
from app.services.library_catalogue import (  # noqa: F401 (the catalogue, re-exported)
    KINDS,
    LibraryItem,
    find,
    installed,
    item_file,
    items,
    labels_for,
    manifest,
)
from app.services.storage import StorageProvider
from app.services.visual_assets import store_visual_upload


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
