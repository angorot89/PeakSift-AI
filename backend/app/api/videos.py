import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Storage
from app.core.config import get_settings
from app.models import Project, Video
from app.schemas.video import VideoRead
from app.services.video_processing import process_video_metadata
from app.services.video_upload import UploadValidationError, check_declared_size, store_upload
from app.services.workspace import scratch_directory

router = APIRouter(prefix="/projects/{project_id}/videos", tags=["videos"])


def get_owned_project(project_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Project:
    """The project if it belongs to the current user; otherwise an indistinguishable 404."""
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


OwnedProject = Annotated[Project, Depends(get_owned_project)]


def reject_oversized_body(request: Request) -> None:
    # Runs before the multipart body is parsed, so an announced oversize upload is
    # refused without being received.
    try:
        check_declared_size(
            request.headers.get("content-length"), get_settings().max_video_upload_bytes
        )
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=VideoRead,
    dependencies=[Depends(reject_oversized_body)],
)
def upload_video(
    project: OwnedProject,
    db: DbSession,
    storage: Storage,
    file: Annotated[UploadFile, File()],
) -> Video:
    settings = get_settings()
    # The upload is spooled locally (size-limited), stored, then probed from the spool.
    with scratch_directory(settings, "uploads") as spool_dir:
        try:
            video, local = store_upload(
                db, storage, project, file, max_bytes=settings.max_video_upload_bytes,
                spool_dir=spool_dir,
            )  # fmt: skip
        except UploadValidationError as error:
            raise HTTPException(status_code=error.status_code, detail=error.message) from None

        # Synchronous for Milestone 2: the response already carries ready/failed.
        return process_video_metadata(db, storage, video, local_copy=local)


@router.get("", response_model=list[VideoRead])
def list_videos(project: OwnedProject, db: DbSession) -> list[Video]:
    """The project's videos, newest first."""
    statement = (
        select(Video)
        .where(Video.project_id == project.id)
        .order_by(Video.created_at.desc(), Video.id.desc())
    )
    return list(db.scalars(statement))


@router.get("/{video_id}", response_model=VideoRead)
def get_video(video_id: uuid.UUID, project: OwnedProject, db: DbSession) -> Video:
    video = db.scalar(select(Video).where(Video.id == video_id, Video.project_id == project.id))
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return video
