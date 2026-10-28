"""What the Copilot model may answer, and how PeakSift checks it.

The model answers one JSON object: ``message`` (the answer, built from the facts it was given),
an optional ``suggestion`` (an opinion, shown apart from the facts), up to three ``actions`` and
up to four ``references``. Actions and references name objects only by the **handles** of the
context (``moment_1``, ``visual_2``…); the server maps them to real objects and drops anything
else — an unknown action type, an invented handle, a handle of the wrong kind. Labels shown on
buttons and chips are written by PeakSift, never by the model. Text that mentions a handle
("moment_1 is strongest") reads its name instead; links are reduced to their text.

Nothing here can publish, delete, disconnect or change anything: the action types are
navigation and the creator's own existing, non-destructive steps, each re-validated on use.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.copilot.context import Target
from app.services.strategy import ANGLES, STYLES

MESSAGE_MAX_CHARS = 900
SUGGESTION_MAX_CHARS = 400
MAX_ACTIONS = 3
MAX_REFERENCES = 4
QUERY_MAX_CHARS = 60

# Action type → the target kinds it accepts (None: an action without a target).
ACTION_TYPES: dict[str, tuple[str, ...] | None] = {
    "open_home": None,
    "new_project": None,
    "open_analytics": None,
    "open_project": ("project",),
    "open_source": ("project",),
    "open_moments": ("project",),
    "open_assets": ("project",),
    "search_assets": ("project",),
    "open_project_analytics": ("project",),
    "create_short": ("moment",),
    "open_create": ("clip", "moment"),
    "open_auto_edit": ("clip", "draft", "moment"),
    "open_editor": ("clip", "short", "moment"),
    "open_short": ("short",),
    "open_published": ("published",),
}


class CopilotOutputError(Exception):
    """The model's answer is not a usable JSON object of the required shape."""


@dataclass(frozen=True)
class ProposedAction:
    type: str
    target: Target | None
    query: str | None = None


@dataclass
class ParsedReply:
    message: str
    suggestion: str | None
    actions: list[ProposedAction]
    references: list[Target]
    dropped: int = 0  # proposals refused (unknown type, invented or mismatched handle…)
    notes: list[str] = field(default_factory=list)


def output_schema(*, ideas: bool = False) -> dict[str, Any]:
    """The JSON schema given to the model (Ollama ``format``). For an ideas question, 3–5
    ``ideas`` are required (small models skip optional fields)."""
    schema = _schema()
    if ideas:
        schema["required"] = [*schema["required"], "ideas"]
        schema["properties"]["ideas"]["minItems"] = 3
        schema["properties"]["ideas"]["maxItems"] = 5
    return schema


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "suggestion": {"type": ["string", "null"]},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": sorted(ACTION_TYPES)},
                        "handle": {"type": "string"},
                        "query": {"type": "string"},
                    },
                    "required": ["type"],
                },
            },
            "references": {"type": "array", "items": {"type": "string"}},
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "moment": {"type": "string"},
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "angle": {"type": "string", "enum": list(ANGLES)},
                        "why": {"type": "string"},
                        "style": {"type": "string", "enum": list(STYLES)},
                    },
                    "required": ["title", "why"],
                },
            },
        },
        "required": ["message", "actions", "references"],
    }


_LINK = re.compile(r"\[([^\]]{1,200})\]\((?:[^)\s]{1,500})\)")
_URL = re.compile(r"https?://\S+")
_HANDLE = re.compile(r"\b(project|moment|short|draft|clip|visual|published|insight)_\d{1,3}\b")
_SPACE = re.compile(r"[ \t]+")
# "(handle: project)", "handle: moment_2" — the model talking about handles instead of names.
_HANDLE_TALK = re.compile(r"\s*\((?:the\s+)?handles?\s*[:=][^)]{0,80}\)|\bhandles?\s*[:=]\s*", re.I)


def _name(target: Target) -> str:
    """A handle's readable name inside a sentence ("Moment: The night before" → "The night
    before")."""
    label = target.label
    return label.split(": ", 1)[1] if ": " in label else label


def clean_text(text: str, targets: dict[str, Target], limit: int) -> str:
    text = _HANDLE_TALK.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _HANDLE.sub(
        lambda m: f"“{_name(targets[m.group(0)])}”" if m.group(0) in targets else "", text
    )
    text = text.replace("**", "").replace("__", "").replace("`", "")
    lines = [_SPACE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
    return (cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…").strip()


def parse_reply(data: Any, targets: dict[str, Target]) -> ParsedReply:
    """Turn the model's JSON into what PeakSift may show. Raises ``CopilotOutputError`` only
    when there is no usable message; everything else that does not check out is dropped."""
    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        raise CopilotOutputError("The answer has no message")
    message = clean_text(data["message"], targets, MESSAGE_MAX_CHARS)
    if not message:
        raise CopilotOutputError("The answer's message is empty")
    raw_suggestion = data.get("suggestion")
    suggestion = None
    if isinstance(raw_suggestion, str) and raw_suggestion.strip():
        suggestion = clean_text(raw_suggestion, targets, SUGGESTION_MAX_CHARS) or None
        if suggestion and suggestion.lower() == message.lower():
            suggestion = None
    dropped = 0
    actions: list[ProposedAction] = []
    seen: set[tuple] = set()
    for item in data.get("actions") or []:
        action = _action(item, targets)
        if action is None:
            dropped += 1
            continue
        key = (action.type, action.target.id if action.target else None, action.query)
        if key in seen:
            continue
        seen.add(key)
        if len(actions) < MAX_ACTIONS:
            actions.append(action)
    references: list[Target] = []
    for handle in data.get("references") or []:
        target = targets.get(handle) if isinstance(handle, str) else None
        if target is None:
            dropped += 1
        elif target not in references and len(references) < MAX_REFERENCES:
            references.append(target)
    return ParsedReply(message, suggestion, actions, references, dropped)


def _action(item: Any, targets: dict[str, Target]) -> ProposedAction | None:
    if not isinstance(item, dict) or item.get("type") not in ACTION_TYPES:
        return None
    kind = item["type"]
    allowed = ACTION_TYPES[kind]
    handle = item.get("handle")
    target = None
    if allowed is not None:
        if handle is None and "project" in allowed:
            handle = "project"  # project actions default to the current project
        target = targets.get(handle) if isinstance(handle, str) else None
        if target is None or target.kind not in allowed:
            return None
    query = None
    if kind == "search_assets":
        raw = item.get("query")
        if not isinstance(raw, str):
            return None
        query = " ".join(re.findall(r"[\w'-]+", raw))[:QUERY_MAX_CHARS].strip()
        if not query:
            return None
    return ProposedAction(kind, target, query)
