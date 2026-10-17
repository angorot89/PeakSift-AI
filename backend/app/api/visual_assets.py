"""Private, project-scoped visual assets (images and B-roll videos): upload, list and search,
metadata, a thumbnail and an owner-only preview stream (HTTP Range, for the editor).

Ownership chain: User → Project → VisualAsset; anything else is a 404 (401 without a session).
Uploads are validated by content (Pillow / ffprobe), not by name, and stored under generated
keys. Creators are responsible for the rights to what they upload; PeakSift ships no stock
library and never fetches media from the internet.
"""

import uuid
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import object_present, stream_object
from app.api.videos import OwnedProject
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import VisualAsset, VisualAssetKind
from app.schemas.project import MediaDeletionRead
from app.schemas.visual_asset import VisualAssetRead, VisualUploadLimits
from app.services.media_deletion import delete_visual_asset, edits_using_visual_asset
from app.services.video_upload import UploadValidationError, check_declared_size
from app.services.visual_assets import ACCEPTED_EXTENSIONS, store_visual_upload
from app.services.visuals.layout import layout_summary

router = APIRouter(prefix="/projects/{project_id}/visual-assets", tags=["visuals"])
limits_router = APIRouter(tags=["visuals"])

MAX_LIST = 200
MAX_QUERY_LENGTH = 100


def get_owned_visual(asset_id: uuid.UUID, project: OwnedProject, db: DbSession) -> VisualAsset:
    asset = db.scalar(
        select(VisualAsset).where(VisualAsset.id == asset_id, VisualAsset.project_id == project.id)
    )
    if asset is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Visual not found")
    return asset


OwnedVisual = Annotated[VisualAsset, Depends(get_owned_visual)]


def reject_oversized_body(request: Request) -> None:
    # Runs before the multipart body is parsed: an announced oversize upload is refused unread.
    try:
        check_declared_size(
            request.headers.get("content-length"), get_settings().visual_asset_max_bytes
        )
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None


def _read(asset: VisualAsset) -> VisualAssetRead:
    return VisualAssetRead.model_validate(asset)


@limits_router.get("/visual-upload-limits", response_model=VisualUploadLimits)
def upload_limits(_: CurrentUser) -> VisualUploadLimits:
    settings = get_settings()
    return VisualUploadLimits(
        max_bytes=settings.visual_asset_max_bytes,
        max_video_duration_seconds=settings.visual_asset_max_video_duration_seconds,
        max_image_pixels=settings.visual_asset_max_pixel_count,
        max_video_pixels=settings.visual_asset_max_video_pixel_count,
        accepted_extensions=list(ACCEPTED_EXTENSIONS),
    )


@limits_router.get("/visual-layout")
def visual_layout(_: CurrentUser) -> dict:
    """Where picture-in-picture and overlays sit in the 1080 × 1920 short (the renderer's
    numbers), so the editor's preview places them the same way."""
    return layout_summary()


@router.post(
    "",
    status_code=http_status.HTTP_201_CREATED,
    response_model=VisualAssetRead,
    dependencies=[per_user("visual_upload"), Depends(reject_oversized_body)],
)
def upload_visual(
    project: OwnedProject,
    db: DbSession,
    storage: Storage,
    response: Response,
    file: Annotated[UploadFile, File()],
) -> VisualAssetRead:
    """Upload an image or a video. The same file again returns the existing asset (200)."""
    try:
        asset, created = store_visual_upload(db, storage, project, file, get_settings())
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None
    if not created:
        response.status_code = http_status.HTTP_200_OK
    return _read(asset)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=list[VisualAssetRead])
def list_visuals(
    project: OwnedProject,
    db: DbSession,
    kind: Annotated[VisualAssetKind | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST)] = MAX_LIST,
) -> list[VisualAssetRead]:
    """The project's visuals, newest first; optionally one kind and a name search."""
    statement = select(VisualAsset).where(VisualAsset.project_id == project.id)
    if kind is not None:
        statement = statement.where(VisualAsset.kind == kind.value)
    words = (q or "").split()
    for word in words:  # every word must appear in the name (case-insensitive)
        statement = statement.where(
            VisualAsset.display_name.ilike(f"%{_escape_like(word)}%", escape="\\")
        )
    statement = statement.order_by(VisualAsset.created_at.desc(), VisualAsset.id).limit(limit)
    return [_read(asset) for asset in db.scalars(statement)]


@router.get("/{asset_id}", response_model=VisualAssetRead)
def get_visual(asset: OwnedVisual) -> VisualAssetRead:
    return _read(asset)


@router.delete("/{asset_id}", response_model=MediaDeletionRead)
def delete_visual(asset: OwnedVisual, db: DbSession, storage: Storage) -> MediaDeletionRead:
    """Delete a visual the project no longer uses. Refused (409) while any edit still
    references it: rendered and future edits must never lose an input."""
    users = edits_using_visual_asset(db, asset)
    if users:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"This visual is used by {users} edit{'s' if users != 1 else ''}; "
            "delete those edits first",
        )
    report = delete_visual_asset(db, storage, asset)
    return MediaDeletionRead(
        media_files_removed=report.deleted, media_files_pending_cleanup=report.failed
    )


@router.get("/{asset_id}/content")
def visual_content(asset: OwnedVisual, request: Request, storage: Storage) -> StreamingResponse:
    """The stored file (the normalized rendition for images), for in-editor preview. Owner
    only; supports a single Range. Served inline with private, no-store caching."""
    if not object_present(storage, asset.storage_key):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Visual file is missing"
        )
    # The served name keeps the creator's name with the stored rendition's extension.
    stem = PurePosixPath(asset.display_name).stem or "visual"
    extension = PurePosixPath(asset.storage_key).suffix
    return stream_object(
        storage, asset.storage_key, request, media_type=asset.content_type,
        filename=f"{stem}{extension}",
    )  # fmt: skip


@router.get("/{asset_id}/thumbnail")
def visual_thumbnail(asset: OwnedVisual, request: Request, storage: Storage) -> StreamingResponse:
    key = asset.thumbnail_storage_key
    if not key or not object_present(storage, key):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Thumbnail is missing"
        )
    media_type = "image/png" if key.endswith(".png") else "image/jpeg"
    return stream_object(storage, key, request, media_type=media_type, filename="thumbnail")
