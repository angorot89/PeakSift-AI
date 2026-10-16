"""Private, project-scoped audio assets (music and sound effects): upload, list, metadata,
waveform peaks and an owner-only preview stream (HTTP Range, for the editor's players).

Ownership chain: User → Project → AudioAsset; anything else is a 404 (401 without a session).
Uploads are validated by content (ffprobe), not by name, and stored under generated keys.
Users are responsible for the rights to what they upload; PeakSift ships no audio library.
"""

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import object_present, stream_object
from app.api.videos import OwnedProject
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import AudioAsset, AudioAssetKind
from app.schemas.audio_asset import AudioAssetRead, AudioUploadLimits, AudioWaveformRead
from app.schemas.project import MediaDeletionRead
from app.services.audio_assets import ACCEPTED_EXTENSIONS, store_audio_upload
from app.services.media_deletion import delete_audio_asset, edits_using_asset
from app.services.video_upload import UploadValidationError, check_declared_size

router = APIRouter(prefix="/projects/{project_id}/audio-assets", tags=["audio"])
limits_router = APIRouter(tags=["audio"])


def get_owned_asset(asset_id: uuid.UUID, project: OwnedProject, db: DbSession) -> AudioAsset:
    asset = db.scalar(
        select(AudioAsset).where(AudioAsset.id == asset_id, AudioAsset.project_id == project.id)
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")
    return asset


OwnedAudioAsset = Annotated[AudioAsset, Depends(get_owned_asset)]


def reject_oversized_body(request: Request) -> None:
    # Runs before the multipart body is parsed: an announced oversize upload is refused unread.
    try:
        check_declared_size(
            request.headers.get("content-length"), get_settings().audio_upload_max_bytes
        )
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None


@limits_router.get("/audio-upload-limits", response_model=AudioUploadLimits)
def upload_limits(_: CurrentUser) -> AudioUploadLimits:
    settings = get_settings()
    return AudioUploadLimits(
        max_bytes=settings.audio_upload_max_bytes,
        music_max_duration_seconds=settings.audio_upload_max_duration_seconds,
        sfx_max_duration_seconds=settings.audio_sfx_max_duration_seconds,
        accepted_extensions=list(ACCEPTED_EXTENSIONS),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AudioAssetRead,
    dependencies=[per_user("audio_upload"), Depends(reject_oversized_body)],
)
def upload_audio(
    project: OwnedProject,
    db: DbSession,
    storage: Storage,
    response: Response,
    file: Annotated[UploadFile, File()],
    kind: Annotated[AudioAssetKind, Form()],
) -> AudioAsset:
    """Upload music or a sound effect. The same file again (same kind) returns it (200)."""
    try:
        asset, created = store_audio_upload(db, storage, project, file, kind, get_settings())
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return asset


@router.get("", response_model=list[AudioAssetRead])
def list_audio(
    project: OwnedProject, db: DbSession, kind: Annotated[AudioAssetKind | None, Query()] = None
) -> list[AudioAsset]:
    """The project's audio, newest first (optionally one kind)."""
    statement = select(AudioAsset).where(AudioAsset.project_id == project.id)
    if kind is not None:
        statement = statement.where(AudioAsset.kind == kind.value)
    return list(db.scalars(statement.order_by(AudioAsset.created_at.desc(), AudioAsset.id)))


@router.get("/{asset_id}", response_model=AudioAssetRead)
def get_audio(asset: OwnedAudioAsset) -> AudioAsset:
    return asset


@router.get("/{asset_id}/waveform", response_model=AudioWaveformRead)
def get_waveform(asset: OwnedAudioAsset) -> AudioWaveformRead:
    peaks = [int(p) for p in asset.waveform_peaks]
    return AudioWaveformRead(
        asset_id=asset.id, duration_seconds=asset.duration_seconds, buckets=len(peaks), peaks=peaks
    )


@router.delete("/{asset_id}", response_model=MediaDeletionRead)
def delete_audio(asset: OwnedAudioAsset, db: DbSession, storage: Storage) -> MediaDeletionRead:
    """Delete an audio file the project no longer uses. Refused (409) while any edit's audio
    section still references it: rendered and future edits must never lose an input."""
    users = edits_using_asset(db, asset)
    if users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This audio is used by {users} edit{'s' if users != 1 else ''}; "
            "delete those edits first",
        )
    report = delete_audio_asset(db, storage, asset)
    return MediaDeletionRead(
        media_files_removed=report.deleted, media_files_pending_cleanup=report.failed
    )


@router.get("/{asset_id}/content")
def audio_content(asset: OwnedAudioAsset, request: Request, storage: Storage) -> StreamingResponse:
    """The uploaded file, for in-editor preview. Owner only; supports a single Range.

    Served inline with private, no-store caching; there is no public URL.
    """
    if not object_present(storage, asset.storage_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file is missing")
    return stream_object(
        storage,
        asset.storage_key,
        request,
        media_type=asset.content_type,
        filename=asset.display_name,
    )
