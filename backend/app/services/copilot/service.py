"""Asking the Copilot: context → model → checked answer → conversation.

The creator's question is saved first, so it is never lost. The context is built for the page
the creator is on; the model answers through the provider; ``contract.parse_reply`` keeps only
what checks out. When the local assistant cannot answer (offline, too slow, unusable answer),
PeakSift says so in plain words — the rest of the product never depends on it. No database
connection is held while the model thinks.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CopilotMessage, User
from app.services.copilot import history
from app.services.copilot.context import CopilotContext, Target, build_context
from app.services.copilot.contract import CopilotOutputError, ParsedReply, parse_reply
from app.services.copilot.prompt import build_messages
from app.services.copilot.provider import CopilotProvider, CopilotProviderError, get_provider

logger = logging.getLogger(__name__)

UNAVAILABLE = "PeakSift's local assistant isn't available right now."
UNUSABLE = "PeakSift's local assistant couldn't give a usable answer this time. Please try again."


@dataclass
class Exchange:
    question: CopilotMessage
    answer: CopilotMessage


def reference_record(target: Target) -> dict:
    return {"kind": target.kind, "label": target.label}


def ask(
    db: Session,
    user: User,
    settings: Settings,
    *,
    text: str,
    page: str,
    project_id: uuid.UUID | None = None,
    clip_id: uuid.UUID | None = None,
    edit_id: uuid.UUID | None = None,
    provider: CopilotProvider | None = None,
) -> Exchange:
    context = build_context(
        db,
        user,
        settings,
        page=page,
        project_id=project_id,
        clip_id=clip_id,
        edit_id=edit_id,
        question=text,
    )
    thread = history.get_or_create_thread(db, user.id, context.project_id)
    turns = history.prompt_turns(db, thread)
    question = history.append(db, thread, role="user", content=text, page=context.page)
    db.commit()  # the question is kept whatever happens next; no connection held while thinking

    parsed: ParsedReply | None = None
    status, content = "unavailable", UNAVAILABLE
    try:
        reply = (provider or get_provider(settings)).reply(build_messages(context, text, turns))
        parsed = parse_reply(reply.data, context.targets)
        status, content = "ok", parsed.message
        if parsed.dropped:
            logger.info("Copilot dropped %d unusable proposal(s)", parsed.dropped)
    except CopilotProviderError as error:
        logger.warning("Copilot answered without the local assistant: %s", error.code)
        if error.code == "malformed":
            content = UNUSABLE
    except CopilotOutputError:
        logger.warning("Copilot answer had no usable message")
        content = UNUSABLE

    actions, refs, suggestion = [], [], None
    if parsed is not None:
        from app.services.copilot.actions import offer

        actions = offer(db, user, parsed.actions)
        refs = [reference_record(t) for t in parsed.references]
        suggestion = parsed.suggestion
    actions = actions or fallback_actions(db, user, context, status)
    answer = history.append(
        db,
        thread,
        role="assistant",
        content=content,
        page=context.page,
        suggestion=suggestion,
        actions=actions,
        refs=refs,
        status=status,
    )
    db.commit()
    return Exchange(question, answer)


def fallback_actions(db: Session, user: User, context: CopilotContext, status: str) -> list[dict]:
    """Without the local assistant, PeakSift still offers its own deterministic next step."""
    if status == "ok":
        return []
    from app.services.copilot.actions import next_step_actions

    return next_step_actions(db, user, context)
