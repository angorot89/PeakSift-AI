"""Authenticated preview and download of rendered clips.

Both endpoints resolve the clip through its owner (Clip → Video → Project → User); any
clip that is not the caller's — or does not exist — is a 404, and so is a clip that is
not ``ready`` or whose artifact is missing. The file location comes only from the stored
key via ``LocalMediaStorage.path_for``; the request never supplies a path. The download
name is a sanitised slug of the candidate title; the title never becomes a storage path.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import stream_file
from app.models import Clip, ClipStatus, Project, Video
from app.services.clip_render.storage import safe_download_filename
from app.services.storage import InvalidStorageKey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])


def _owned_ready_clip(clip_id: uuid.UUID, user_id: uuid.UUID, db, storage):
    clip = db.scalar(
        select(Clip)
        .join(Video, Clip.video_id == Video.id)
        .join(Project, Video.project_id == Project.id)
        .where(Clip.id == clip_id, Project.user_id == user_id)
    )
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")
    if clip.status != ClipStatus.READY or not clip.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip is not ready")
    try:
        path = storage.path_for(clip.storage_key)
    except InvalidStorageKey:
        logger.error("Clip %s has an invalid storage key", clip.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Clip file not found"
        ) from None
    if not path.is_file():
        logger.error("Clip %s is ready but its artifact is missing", clip.id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip file not found")
    return clip, path


@router.get("/{clip_id}/content")
def clip_content(
    clip_id: uuid.UUID, request: Request, current_user: CurrentUser, db: DbSession, storage: Storage
) -> StreamingResponse:
    """Inline, Range-capable stream for the browser's <video> element."""
    clip, path = _owned_ready_clip(clip_id, current_user.id, db, storage)
    name = safe_download_filename(clip.candidate.title, clip.id)
    return stream_file(path, request, media_type=clip.content_type, filename=name)


@router.get("/{clip_id}/download")
def clip_download(
    clip_id: uuid.UUID, request: Request, current_user: CurrentUser, db: DbSession, storage: Storage
) -> StreamingResponse:
    """The same bytes as an attachment with a safe, human-friendly filename."""
    clip, path = _owned_ready_clip(clip_id, current_user.id, db, storage)
    name = safe_download_filename(clip.candidate.title, clip.id)
    return stream_file(path, request, media_type=clip.content_type, filename=name, attachment=True)
