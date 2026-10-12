import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Project
from app.schemas.project import ProjectCreate, ProjectRead

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
