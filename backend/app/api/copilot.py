"""Creator Copilot (V1.6).

``GET /copilot/context`` says what the assistant can see from the current page: the scope (the
workspace or one project) and a few facts. The context itself — built by
``services/copilot/context.py`` from the creator's own rows, with symbolic handles — stays on the
server. Another creator's project or clip is a ``404``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.schemas.copilot import CopilotContextRead
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
