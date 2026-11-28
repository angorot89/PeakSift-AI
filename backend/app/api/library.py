"""PeakSift's built-in starter library: browse it, listen or look, and add an item to a project.

``GET /library`` is the catalogue (titles, categories, licences and credits — never paths or
digests); ``GET /library/{id}/content`` serves an installed, verified file to signed-in users;
``POST /projects/{project_id}/library/{id}`` imports an item into the project as an ordinary
audio or visual asset (see ``services/library.py``).
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.videos import OwnedProject
from app.api.visual_assets import _read as read_visual
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.schemas.audio_asset import AudioAssetRead
from app.schemas.visual_asset import VisualAssetRead
from app.services import library
from app.services.semantic.lifecycle import start_indexing_quietly
from app.services.video_upload import UploadValidationError

router = APIRouter(tags=["library"])

LICENCE_LABELS = {"CC0-1.0": "CC0 (no rights reserved)", "MIT": "MIT licence"}
KIND_LABELS = {
    "sfx": "Sound effects",
    "music": "Music",
    "sticker": "Stickers",
    "overlay": "Animated overlays",
}


class LibraryItemRead(BaseModel):
    id: str
    kind: Literal["sfx", "music", "sticker", "overlay"]
    title: str
    category: str
    tags: list[str]
    duration_seconds: float | None
    licence: str
    credit: str
    source_name: str
    source_url: str


class LibrarySourceRead(BaseModel):
    name: str
    url: str
    licence: str


class LibraryRead(BaseModel):
    # False when this server has not installed the library (nothing can be previewed or added).
    available: bool
    items: list[LibraryItemRead]
    sources: list[LibrarySourceRead]


class LibraryImportRead(BaseModel):
    kind: Literal["audio", "visual"]
    created: bool
    audio_asset: AudioAssetRead | None = None
    visual_asset: VisualAssetRead | None = None


def _item_or_404(item_id: str) -> library.LibraryItem:
    item = library.find(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return item


@router.get("/library", response_model=LibraryRead)
def get_library(_user: CurrentUser) -> LibraryRead:
    settings = get_settings()
    catalogue = library.items()
    sources: dict[str, LibrarySourceRead] = {}
    for item in catalogue:
        name = item.source_name
        url = item.source_url if name != "OpenGameArt.org" else "https://opengameart.org"
        sources.setdefault(
            name, LibrarySourceRead(name=name, url=url, licence=LICENCE_LABELS[item.licence])
        )
    return LibraryRead(
        available=library.installed(settings.library_dir),
        items=[
            LibraryItemRead(
                id=item.id,
                kind=item.kind,  # type: ignore[arg-type]
                title=item.title,
                category=item.category,
                tags=list(item.tags),
                duration_seconds=item.duration_seconds,
                licence=LICENCE_LABELS[item.licence],
                credit=item.credit,
                source_name=item.source_name,
                source_url=item.source_url,
            )
            for item in catalogue
        ],
        sources=list(sources.values()),
    )


@router.get("/library/{item_id}/content")
def get_library_content(item_id: str, _user: CurrentUser) -> FileResponse:
    item = _item_or_404(item_id)
    path = library.item_file(item, get_settings().library_dir)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The library is not installed here"
        )
    return FileResponse(
        path,
        media_type=item.content_type,
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/projects/{project_id}/library/{item_id}",
    response_model=LibraryImportRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("library_import")],
)
def import_library_item(
    item_id: str, project: OwnedProject, db: DbSession, storage: Storage, response: Response
) -> LibraryImportRead:
    """Add a library item to the project's audio or visuals (labelled with its licence). The
    same item again returns the project's existing asset (200)."""
    settings = get_settings()
    item = _item_or_404(item_id)
    try:
        asset, created = library.import_into(db, storage, project, item, settings)
    except library.LibraryItemUnavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The PeakSift library is not installed on this server",
        ) from None
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    if item.kind in ("sticker", "overlay"):
        start_indexing_quietly(db, asset, settings)
        return LibraryImportRead(kind="visual", created=created, visual_asset=read_visual(asset))
    return LibraryImportRead(
        kind="audio", created=created, audio_asset=AudioAssetRead.model_validate(asset)
    )
