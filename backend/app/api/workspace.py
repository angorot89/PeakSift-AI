"""Workspace summaries (V1.5): ``GET /workspace/home`` and ``GET /projects/{id}/summary``.

Read-only, owner-scoped (another creator's project is a ``404``), and built from existing rows
by ``services/workspace_summary.py``: what exists and in which state — the frontend decides the next
step from these facts.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Project
from app.schemas.workspace import HomeRead, ProjectSummaryRead
from app.services import workspace_summary as workspace

router = APIRouter(tags=["workspace"])


@router.get("/workspace/home", response_model=HomeRead)
def workspace_home(current_user: CurrentUser, db: DbSession) -> dict:
    return workspace.home(db, current_user.id)


@router.get("/projects/{project_id}/summary", response_model=ProjectSummaryRead)
def project_summary(project_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> dict:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return workspace.project_summary(db, project)
