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
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import object_present, stream_object
from app.api.videos import OwnedProject
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import VisualAsset, VisualAssetKind
from app.schemas.project import MediaDeletionRead
from app.schemas.visual_asset import (
    VisualAssetRead,
    VisualAssetUpdate,
    VisualMatchRead,
    VisualSearchHit,
    VisualSearchRead,
    VisualSearchResults,
    VisualUploadLimits,
)
from app.services.branding.profiles import brands_using_logo
from app.services.media_deletion import delete_visual_asset, edits_using_visual_asset
from app.services.semantic.indexing import TooManyAttempts
from app.services.semantic.lifecycle import (
    start_indexing,
    start_indexing_quietly,
    start_lazy_indexing,
    visual_search_status,
)
from app.services.semantic.registry import configured_identity
from app.services.semantic.search import clean_query, search_project
from app.services.semantic.state import SemanticState, semantic_state
from app.services.video_upload import UploadValidationError, check_declared_size
from app.services.visual_assets import (
    ACCEPTED_EXTENSIONS,
    clean_description,
    clean_display_name,
    clean_tags,
    store_visual_upload,
)
from app.services.visuals.layout import layout_summary

router = APIRouter(prefix="/projects/{project_id}/visual-assets", tags=["visuals"])
limits_router = APIRouter(tags=["visuals"])

MAX_LIST = 200
MAX_QUERY_LENGTH = 100
MAX_SEARCH_INPUT = 200  # longer input is refused; the searched text is at most 100 characters
MAX_SEARCH_RESULTS = 50


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
    status = visual_search_status(asset, get_settings())
    read = VisualAssetRead.model_validate(asset)
    read.visual_search = VisualSearchRead(
        state=status.state.value,
        frames_done=status.frames_done,
        frames_total=status.frames_total,
        message=status.message,
        can_retry=status.can_retry,
    )
    return read


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
    """Upload an image or a video. The same file again returns the existing asset (200).

    Visual search indexing starts in the background (never awaited): the asset is usable by
    hand at once, whatever happens to its indexing."""
    settings = get_settings()
    try:
        asset, created = store_visual_upload(db, storage, project, file, settings)
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None
    if not created:
        response.status_code = http_status.HTTP_200_OK
    start_indexing_quietly(db, asset, settings)
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
    statement = (
        select(VisualAsset)
        .options(selectinload(VisualAsset.semantic_indexes))
        .where(VisualAsset.project_id == project.id)
    )
    if kind is not None:
        statement = statement.where(VisualAsset.kind == kind.value)
    words = (q or "").split()
    for word in words:  # every word must appear in the name, description or tags
        pattern = f"%{_escape_like(word)}%"
        statement = statement.where(
            or_(
                VisualAsset.display_name.ilike(pattern, escape="\\"),
                VisualAsset.description.ilike(pattern, escape="\\"),
                cast(VisualAsset.tags, String).ilike(pattern, escape="\\"),
            )
        )
    statement = statement.order_by(VisualAsset.created_at.desc(), VisualAsset.id).limit(limit)
    assets = list(db.scalars(statement))
    # After a model change, a few stale assets are re-queued per listing (bounded).
    start_lazy_indexing(db, assets, get_settings())
    return [_read(asset) for asset in assets]


@router.get("/search", response_model=VisualSearchResults, dependencies=[per_user("visual_search")])
def search_visuals(
    project: OwnedProject,
    db: DbSession,
    q: Annotated[str, Query(max_length=MAX_SEARCH_INPUT)],
    kind: Annotated[VisualAssetKind | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_RESULTS)] = 20,
) -> VisualSearchResults:
    """Search this project's visuals by what they show and by their names, descriptions and
    tags. Strongest first; only matches are returned (an unrelated asset is never padded in).
    Without visual search (turned off, still preparing, model unavailable) the words still
    match, and the response says so."""
    query = clean_query(q)
    if not query:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Type what you are looking for",
        )
    outcome = search_project(
        db, project.id, query, get_settings(), kind=kind.value if kind else None, limit=limit
    )
    return VisualSearchResults(
        query=query,
        visual_search_used=outcome.visual_used,
        assets_preparing=outcome.preparing,
        results=[
            VisualSearchHit(
                asset=_read(match.asset),
                match=VisualMatchRead(
                    strength=match.strength.value,
                    method=match.method.value,
                    best_frame_time=(
                        round(match.best_frame_time, 1)
                        if match.best_frame_time is not None and match.asset.kind == "video"
                        else None
                    ),
                ),
            )
            for match in outcome.matches
        ],
    )


@router.get("/{asset_id}", response_model=VisualAssetRead)
def get_visual(asset: OwnedVisual) -> VisualAssetRead:
    return _read(asset)


@router.post(
    "/{asset_id}/visual-search/retry",
    response_model=VisualAssetRead,
    dependencies=[per_user("visual_analysis")],
)
def retry_visual_search(asset: OwnedVisual, db: DbSession) -> VisualAssetRead:
    """Analyse the asset again for visual search (no re-upload): after a failure, or when it
    is stale or was never analysed. A ready or running analysis is left as it is."""
    settings = get_settings()
    identity = configured_identity(settings)
    if identity is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Visual search is turned off on this server",
        )
    state = semantic_state(asset.semantic_indexes, identity)
    if state not in (SemanticState.READY, SemanticState.QUEUED, SemanticState.INDEXING):
        try:
            start_indexing(db, asset, settings, retry=state == SemanticState.FAILED)
        except TooManyAttempts:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Visual analysis failed too many times for this file",
            ) from None
        db.expire(asset, ["semantic_indexes"])
    return _read(asset)


@router.patch("/{asset_id}", response_model=VisualAssetRead)
def update_visual(asset: OwnedVisual, body: VisualAssetUpdate, db: DbSession) -> VisualAssetRead:
    """Rename an asset or describe and tag it (words that help match B-roll suggestions).
    The file itself never changes."""
    try:
        if body.display_name is not None:
            asset.display_name = clean_display_name(body.display_name)
        if body.description is not None:
            asset.description = clean_description(body.description)
        if body.tags is not None:
            asset.tags = clean_tags(body.tags)
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None
    db.commit()
    return _read(asset)


@router.delete("/{asset_id}", response_model=MediaDeletionRead)
def delete_visual(asset: OwnedVisual, db: DbSession, storage: Storage) -> MediaDeletionRead:
    """Delete a visual the project no longer uses. Refused (409) while any edit still
    references it (rendered and future edits must never lose an input) or a brand uses it as
    its logo."""
    users = edits_using_visual_asset(db, asset)
    if users:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"This visual is used by {users} edit{'s' if users != 1 else ''}; "
            "delete those edits first",
        )
    brands = brands_using_logo(db, asset)
    if brands:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"This image is the logo of your brand “{brands[0]}”; choose another logo "
            "in Brand Studio first",
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
