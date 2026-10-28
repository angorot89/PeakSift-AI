"""Copilot conversations: one per creator and project (or the workspace), clearable at will.

Only what the creator saw is stored (see ``models/copilot.py``). A thread keeps its most recent
``MAX_MESSAGES`` messages; older ones are pruned as new ones arrive. The model receives at most
the last ``PROMPT_TURNS`` exchanges, as plain text — never earlier contexts or actions.
"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CopilotMessage, CopilotThread

MAX_MESSAGES = 200
PROMPT_TURNS = 6  # messages (3 questions and their answers)


def _scope(project_id: uuid.UUID | None):
    if project_id is None:
        return CopilotThread.project_id.is_(None)
    return CopilotThread.project_id == project_id


def find_thread(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID | None
) -> CopilotThread | None:
    return db.scalar(
        select(CopilotThread).where(CopilotThread.user_id == user_id, _scope(project_id))
    )


def get_or_create_thread(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID | None
) -> CopilotThread:
    thread = find_thread(db, user_id, project_id)
    if thread is not None:
        return thread
    thread = CopilotThread(user_id=user_id, project_id=project_id)
    db.add(thread)
    try:
        db.flush()
    except IntegrityError:  # a concurrent first question created it: use that one
        db.rollback()
        thread = find_thread(db, user_id, project_id)
        assert thread is not None
    return thread


def append(
    db: Session,
    thread: CopilotThread,
    *,
    role: str,
    content: str,
    page: str,
    suggestion: str | None = None,
    actions: list[dict] | None = None,
    refs: list[dict] | None = None,
    status: str = "ok",
) -> CopilotMessage:
    last = db.scalar(
        select(func.max(CopilotMessage.sequence)).where(CopilotMessage.thread_id == thread.id)
    )
    message = CopilotMessage(
        thread_id=thread.id, sequence=(last or 0) + 1, role=role, content=content,
        suggestion=suggestion, page=page, status=status, actions=actions or [], refs=refs or [],
    )  # fmt: skip
    db.add(message)
    db.flush()
    cutoff = message.sequence - MAX_MESSAGES
    if cutoff > 0:
        db.execute(
            delete(CopilotMessage).where(
                CopilotMessage.thread_id == thread.id, CopilotMessage.sequence <= cutoff
            )
        )
    thread.updated_at = func.now()
    return message


def messages(db: Session, thread: CopilotThread, limit: int = 50) -> list[CopilotMessage]:
    rows = db.scalars(
        select(CopilotMessage)
        .where(CopilotMessage.thread_id == thread.id)
        .order_by(CopilotMessage.sequence.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def prompt_turns(db: Session, thread: CopilotThread) -> list[dict[str, str]]:
    """The last exchanges as plain text for the model (answers without their actions)."""
    return [
        {"role": m.role, "content": m.content}
        for m in messages(db, thread, PROMPT_TURNS)
        if m.status == "ok"
    ]


def clear(db: Session, user_id: uuid.UUID, project_id: uuid.UUID | None) -> bool:
    """Delete one conversation (thread and messages) and nothing else."""
    thread = find_thread(db, user_id, project_id)
    if thread is None:
        return False
    db.delete(thread)
    return True
