"""Authenticated streaming of a source video's bytes, with single-range support."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import content_disposition, iter_file, parse_range, stream_file
from app.models import Project, Video

# Re-exported for existing callers/tests; the implementation lives in media_streaming.
__all__ = ["content_disposition", "iter_file", "parse_range", "router"]

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("/{video_id}/content")
def video_content(
    video_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> StreamingResponse:
    video = db.scalar(
        select(Video).join(Project).where(Video.id == video_id, Project.user_id == current_user.id)
    )
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    path = storage.path_for(video.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video file not found")
    return stream_file(
        path, request, media_type=video.content_type, filename=video.original_filename
    )
