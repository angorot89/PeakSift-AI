import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Storage
from app.models import Project, Transcription, TranscriptSegment, Video
from app.schemas.project import (
    MediaDeletionRead,
    ProjectCreate,
    ProjectDelete,
    ProjectRead,
    ProjectUpdate,
)
from app.services import language, markets
from app.services.media_deletion import delete_project as delete_project_and_media

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(current_user: CurrentUser, db: DbSession) -> list[Project]:
    """The current user's projects, newest first."""
    statement = (
        select(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    return list(db.scalars(statement))


def _market_fields(market: str | None, language: str | None) -> dict:
    fields = {}
    try:
        if market is not None:
            fields["market"] = markets.market(market).code
        if language is not None:
            fields["content_language"] = markets.content_language(language)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    return fields


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectRead)
def create_project(payload: ProjectCreate, current_user: CurrentUser, db: DbSession) -> Project:
    # A new project starts in the creator's default market unless they chose another.
    fields = _market_fields(payload.market or current_user.default_market, payload.content_language)
    project = Project(name=payload.name, owner=current_user, **fields)
    db.add(project)
    db.commit()
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Project:
    # Scoped to the owner so another user's project is indistinguishable from a missing one.
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, current_user: CurrentUser, db: DbSession
) -> Project:
    """Change the project's market or content language (the creator's explicit choice). Shorts
    already made keep the market they were made with (frozen in their provenance)."""
    project = get_project(project_id, current_user, db)
    for name, value in _market_fields(payload.market, payload.content_language).items():
        setattr(project, name, value)
    db.commit()
    return project


@router.get("/{project_id}/language")
def project_language(project_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> dict:
    """The project's content language: the creator's choice (which always wins) and, from its
    newest transcript, what the speech is *likely* in — never a certainty."""
    project = get_project(project_id, current_user, db)
    text = db.execute(
        select(func.string_agg(TranscriptSegment.text, " "))
        .join(Transcription, Transcription.id == TranscriptSegment.transcription_id)
        .join(Video, Video.id == Transcription.video_id)
        .where(Video.project_id == project.id, Transcription.status == "completed")
    ).scalar()
    guess = language.detect(text or "")
    chosen = project.content_language
    return {
        "chosen": chosen,
        "detected": {**guess.read(), "label": language.label(guess)},
        "effective": chosen
        if chosen != "auto"
        else (guess.language if guess.language != "unknown" else None),
    }


@router.delete("/{project_id}", response_model=MediaDeletionRead)
def delete_project(
    project_id: uuid.UUID,
    payload: ProjectDelete,
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> MediaDeletionRead:
    """Permanently delete a project, everything in it and its media files.

    The body must repeat the project's exact name. Rows go first in one commit, then the
    files; any file that cannot be removed now is reported and left for the storage cleanup.
    """
    project = get_project(project_id, current_user, db)
    if payload.confirm_name != project.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Type the project's exact name to confirm deletion",
        )
    report = delete_project_and_media(db, storage, project)
    return MediaDeletionRead(
        media_files_removed=report.deleted, media_files_pending_cleanup=report.failed
    )
