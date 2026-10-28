"""Copilot actions: what an answer may offer the creator to click.

The model proposes actions by type and handle (``contract.ACTION_TYPES``); PeakSift writes every
button label itself and stores the target it resolved, so a click is re-validated against the
current state before anything happens (see ``resolve``). No action type publishes, deletes,
disconnects or changes settings.
"""

from sqlalchemy.orm import Session

from app.models import User
from app.services.copilot.context import CopilotContext
from app.services.copilot.contract import ProposedAction

LABELS = {
    "open_home": "Go to Home",
    "new_project": "Create a project",
    "open_analytics": "Open analytics",
    "open_project": "Open project",
    "open_source": "Open the source video",
    "open_moments": "Review moments",
    "open_assets": "Open visuals",
    "search_assets": "Search visuals",
    "open_project_analytics": "See how this project's Shorts are doing",
    "create_short": "Create Short",
    "open_create": "Create Short",
    "open_auto_edit": "Open Auto Edit",
    "open_editor": "Open the editor",
    "open_short": "Open the Short",
    "open_published": "See its performance",
}


def label_for(action: ProposedAction) -> str:
    label = LABELS[action.type]
    if action.type == "search_assets" and action.query:
        return f"Search visuals for “{action.query}”"
    if action.type == "open_project" and action.target is not None:
        return f"Open {action.target.label}"
    return label


def record(action: ProposedAction, label: str) -> dict:
    target = action.target
    return {
        "type": action.type,
        "label": label,
        "query": action.query,
        "target": None
        if target is None
        else {
            "kind": target.kind,
            "id": str(target.id) if target.id else None,
            "ref": {k: str(v) for k, v in target.ref.items()},
            "label": target.label,
        },
    }


def offer(db: Session, user: User, proposals: list[ProposedAction]) -> list[dict]:
    return [record(action, label_for(action)) for action in proposals]


def next_step_actions(db: Session, user: User, context: CopilotContext) -> list[dict]:
    """PeakSift's own next step, offered when the local assistant cannot answer (filled in by
    the next-action engine)."""
    return []
