"""Creator Copilot (V1.6).

``GET /copilot/thread`` returns the creator's conversation for a project (``project_id``) or for
the workspace (no ``project_id``); ``DELETE /copilot/thread`` clears it (the conversation only —
never the project or anything in it). ``GET /copilot/context`` says what the assistant can see
from the current page: the scope (the workspace or one project) and a few facts. The context
itself — built by ``services/copilot/context.py`` from the creator's own rows, with symbolic
handles — stays on the server. Another creator's project or clip is a ``404``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.models import CopilotMessage, Project
from app.schemas.copilot import (
    CopilotActionRead,
    CopilotContextRead,
    CopilotMessageRead,
    CopilotReferenceRead,
    CopilotThreadRead,
)
from app.services.copilot import history
from app.services.copilot.context import PAGES, ContextNotFound, build_context

router = APIRouter(prefix="/copilot", tags=["copilot"])

Page = Annotated[str, Query(max_length=32)]


def _context(db, user, page, project_id, clip_id, edit_id, question=""):
    try:
        return build_context(
            db, user, get_settings(), page=page if page in PAGES else "home",
            project_id=project_id, clip_id=clip_id, edit_id=edit_id, question=question,
        )  # fmt: skip
    except ContextNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from None


@router.get("/context", response_model=CopilotContextRead)
def copilot_context(
    current_user: CurrentUser,
    db: DbSession,
    page: Page = "home",
    project_id: uuid.UUID | None = None,
    clip_id: uuid.UUID | None = None,
    edit_id: uuid.UUID | None = None,
) -> CopilotContextRead:
    context = _context(db, current_user, page, project_id, clip_id, edit_id)
    return CopilotContextRead(page=context.page, scope=context.scope_label, facts=context.facts)


def _owned_project(db, user, project_id: uuid.UUID | None) -> Project | None:
    if project_id is None:
        return None
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def message_read(message: CopilotMessage) -> CopilotMessageRead:
    return CopilotMessageRead(
        id=message.id, role=message.role, content=message.content,
        suggestion=message.suggestion, status=message.status, page=message.page,
        actions=[CopilotActionRead(index=i, type=a["type"], label=a["label"])
                 for i, a in enumerate(message.actions or [])],
        references=[CopilotReferenceRead(kind=r["kind"], label=r["label"])
                    for r in message.refs or []],
        created_at=message.created_at,
    )  # fmt: skip


@router.get("/thread", response_model=CopilotThreadRead)
def copilot_thread(
    current_user: CurrentUser, db: DbSession, project_id: uuid.UUID | None = None
) -> CopilotThreadRead:
    project = _owned_project(db, current_user, project_id)
    thread = history.find_thread(db, current_user.id, project_id)
    items = history.messages(db, thread) if thread else []
    return CopilotThreadRead(
        scope=project.name if project else "Your workspace",
        messages=[message_read(m) for m in items],
    )


@router.delete("/thread", status_code=status.HTTP_204_NO_CONTENT)
def clear_copilot_thread(
    current_user: CurrentUser, db: DbSession, project_id: uuid.UUID | None = None
) -> Response:
    """Clear one conversation. Idempotent: clearing an empty conversation is fine."""
    _owned_project(db, current_user, project_id)
    history.clear(db, current_user.id, project_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
