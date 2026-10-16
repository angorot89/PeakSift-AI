import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Storage
from app.models import Project
from app.schemas.project import MediaDeletionRead, ProjectCreate, ProjectDelete, ProjectRead
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


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectRead)
def create_project(payload: ProjectCreate, current_user: CurrentUser, db: DbSession) -> Project:
    project = Project(name=payload.name, owner=current_user)
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
