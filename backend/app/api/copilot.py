"""Creator Copilot (V1.6).

``GET /copilot/thread`` returns the creator's conversation for a project (``project_id``) or for
the workspace (no ``project_id``); ``DELETE /copilot/thread`` clears it (the conversation only —
never the project or anything in it). ``GET /copilot/context`` says what the assistant can see
from the current page: the scope (the workspace or one project) and a few facts. The context
itself — built by ``services/copilot/context.py`` from the creator's own rows, with symbolic
handles — stays on the server. Another creator's project or clip is a ``404``.
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import CopilotMessage, CopilotThread, Project
from app.schemas.copilot import (
    CopilotActionRead,
    CopilotActionResolutionRead,
    CopilotAskRequest,
    CopilotCardRead,
    CopilotContextRead,
    CopilotExchangeRead,
    CopilotMessageRead,
    CopilotReferenceRead,
    CopilotStatusRead,
    CopilotThreadRead,
)
from app.services.copilot import history, service
from app.services.copilot.actions import ActionUnavailable, resolve_record
from app.services.copilot.context import PAGES, ContextNotFound, build_context
from app.services.copilot.provider import assistant_available

router = APIRouter(prefix="/copilot", tags=["copilot"])

# Control characters (never part of a question; NUL cannot even be stored), zero-width spaces and
# byte-order marks, and bidirectional overrides that make text display other than it reads.
# Joiners (U+200C/U+200D) stay: emoji sequences and Persian or Arabic text use them.
_INVISIBLE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b\ufeff\u202a-\u202e\u2066-\u2069]")

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
    project = context.view.get("project")
    return CopilotContextRead(
        page=context.page,
        scope=context.scope_label,
        facts=context.facts,
        has_source=project.get("source_video") is not None if isinstance(project, dict) else None,
    )


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
        cards=[CopilotCardRead(**card) for card in message.cards or []],
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


@router.get("/status", response_model=CopilotStatusRead)
def copilot_status(current_user: CurrentUser) -> CopilotStatusRead:
    settings = get_settings()
    return CopilotStatusRead(
        enabled=settings.copilot_enabled, available=assistant_available(settings)
    )


@router.post(
    "/messages",
    response_model=CopilotExchangeRead,
    dependencies=[per_user("copilot_minute"), per_user("copilot_hour")],
)
def ask_copilot(body: CopilotAskRequest, current_user: CurrentUser, db: DbSession):
    """Ask about the current page. The question is saved, the local assistant answers (or
    PeakSift says it cannot right now), and both messages are returned."""
    settings = get_settings()
    if not settings.copilot_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Ask PeakSift is turned off"
        )
    text = _INVISIBLE.sub("", body.text)
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write a question first")
    if len(text) > settings.copilot_message_max_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Questions can be up to {settings.copilot_message_max_chars} characters",
        )
    try:
        exchange = service.ask(
            db,
            current_user,
            settings,
            text=text,
            page=body.page if body.page in PAGES else "home",
            project_id=body.project_id,
            clip_id=body.clip_id,
            edit_id=body.edit_id,
        )
    except ContextNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from None
    except service.QuestionInProgress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PeakSift is still answering your last question here.",
        ) from None
    except service.ConversationCleared:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation was cleared while PeakSift was answering.",
        ) from None
    return CopilotExchangeRead(
        question=message_read(exchange.question), answer=message_read(exchange.answer)
    )


@router.post("/messages/{message_id}/actions/{index}", response_model=CopilotActionResolutionRead)
def resolve_copilot_action(
    message_id: uuid.UUID, index: int, current_user: CurrentUser, db: DbSession
) -> CopilotActionResolutionRead:
    """Re-check an offered action against the current state before the creator follows it.
    ``409`` with a plain reason when its target is gone or no longer usable."""
    message = db.scalar(
        select(CopilotMessage)
        .join(CopilotThread, CopilotThread.id == CopilotMessage.thread_id)
        .where(CopilotMessage.id == message_id, CopilotThread.user_id == current_user.id)
    )
    if message is None or not 0 <= index < len(message.actions or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")
    try:
        resolution = resolve_record(db, current_user, message.actions[index])
    except ActionUnavailable as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
    return CopilotActionResolutionRead(**vars(resolution))
