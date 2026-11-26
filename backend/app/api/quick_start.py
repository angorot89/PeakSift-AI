"""Quick start: one upload becomes a project that is already working.

Home's single step. The creator drops a long video; PeakSift names the project from the file
(or uses the name they typed), stores and checks the video, starts the transcription and marks
it so moment detection follows by itself (``clip_detection/autostart.py``). Every later screen
is the ordinary project — nothing here is a second pipeline.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.projects import _market_fields
from app.api.transcriptions import _configured_model
from app.api.videos import reject_oversized_body
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import Project, Transcription, VideoStatus
from app.schemas.project import ProjectRead
from app.schemas.video import VideoRead
from app.services.quick_start import project_name
from app.services.video_processing import process_video_metadata
from app.services.video_upload import UploadValidationError, store_upload
from app.services.workspace import scratch_directory
from app.workers.dispatch import JobQueueUnavailable, enqueue_transcription, new_task_id

router = APIRouter(prefix="/quick-start", tags=["quick-start"])


class QuickStartRead(BaseModel):
    project: ProjectRead
    video: VideoRead
    # False when the video is not usable or the job queue was down: the project then shows
    # its ordinary next step instead of a job that will never run.
    transcription_started: bool


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=QuickStartRead,
    dependencies=[per_user("video_upload"), Depends(reject_oversized_body)],
)
def quick_start(
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form(max_length=200)] = None,
    market: Annotated[str | None, Form(max_length=16)] = None,
) -> QuickStartRead:
    settings = get_settings()
    fields = _market_fields(market or current_user.default_market, None)
    project = Project(name=project_name(name, file.filename), owner=current_user, **fields)
    db.add(project)

    with scratch_directory(settings, "uploads") as spool_dir:
        try:
            # Commits the project together with its video; a refused upload leaves neither.
            video, local = store_upload(
                db, storage, project, file, max_bytes=settings.max_video_upload_bytes,
                spool_dir=spool_dir,
            )  # fmt: skip
        except UploadValidationError as error:
            db.rollback()
            raise HTTPException(status_code=error.status_code, detail=error.message) from None
        video = process_video_metadata(db, storage, video, local_copy=local)

    started = False
    if video.status == VideoStatus.READY:
        transcription = Transcription(
            video=video,
            provider=settings.transcription_provider,
            model=_configured_model(settings.transcription_provider),
            celery_task_id=new_task_id(),  # fencing token committed before the job exists
            auto_find_moments=True,
        )
        db.add(transcription)
        db.commit()
        try:
            enqueue_transcription(transcription.id, task_id=transcription.celery_task_id)
            started = True
        except JobQueueUnavailable:
            db.delete(transcription)  # never leave a row that no worker will pick up
            db.commit()
    return QuickStartRead(
        project=ProjectRead.model_validate(project),
        video=VideoRead.model_validate(video),
        transcription_started=started,
    )
