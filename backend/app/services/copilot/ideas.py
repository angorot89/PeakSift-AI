"""Short ideas from a source video — only from what the video really contains.

When the creator asks for ideas, the model may return up to five. Each must be anchored in the
context: a **moment handle** (a ranked moment of this video) or a **time range whose start and
end are transcript times shown in DATA**. Anything else is dropped — an idea cannot invent
content. The server writes the card: the moment's real time range, an allow-listed angle
(Lesson, Story, Mistake…) and style (Clean, Punchy, Story, Minimal), the model's short title and
reason (cleaned), and a note when it repeats work ("Similar to a Short you've already
published"). A moment idea comes with *Create Short*.

Without the local assistant, PeakSift builds the cards itself from the video's unused moments
(``strategy.fallback_ideas``).
"""

import re
from dataclasses import dataclass
from typing import Any

from app.services.copilot.context import CopilotContext, Target
from app.services.copilot.contract import ProposedAction, clean_text
from app.services.strategy import ANGLES, STYLES, idea_card

MAX_IDEAS = 5
IDEA_WORDS = re.compile(
    r"\b(ideas?|id[ée]es?|ideen|ideias?)\b|أفكار|فكرة|点子|想法|创意", re.IGNORECASE
)
_TIME = re.compile(r"^\d{1,3}:\d{2}$")


def asks_for_ideas(text: str) -> bool:
    return bool(IDEA_WORDS.search(text))


@dataclass
class IdeaCard:
    card: dict[str, Any]
    action: ProposedAction | None


def _seconds(text: str) -> int:
    minutes, seconds = text.split(":")
    return int(minutes) * 60 + int(seconds)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def check_ideas(raw: Any, context: CopilotContext) -> list[IdeaCard]:
    if not isinstance(raw, list):
        return []
    moments = {
        item["handle"]: item
        for item in ((context.view.get("project") or {}).get("moments") or {}).get("ranked") or []
    }
    times = {line["time"] for line in context.view.get("transcript_excerpt") or []}
    made = [
        (m.start, m.end) for m in (context.strategy.moments if context.strategy else []) if m.made
    ]
    facts = {m.candidate_id: m for m in (context.strategy.moments if context.strategy else [])}
    by_title = {
        _norm(item["title"]): handle for handle, item in moments.items() if item.get("title")
    }
    cards: list[IdeaCard] = []
    seen: set[str] = set()
    for item in raw[: MAX_IDEAS * 2]:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            continue
        title = clean_text(item["title"], context.targets, 100)
        why = clean_text(item.get("why") or "", context.targets, 200) or None
        angle = item.get("angle") if item.get("angle") in ANGLES else None
        style = item.get("style") if item.get("style") in STYLES else None
        handle = item.get("moment")
        if not isinstance(handle, str) or handle not in moments:
            # Small models often name the moment instead of giving its handle: an exact title
            # match (case and spacing aside) anchors the idea to that real moment.
            handle = by_title.get(_norm(item["title"]), handle)
        target: Target | None = context.targets.get(handle) if isinstance(handle, str) else None
        if target is not None and target.kind == "moment" and handle in moments:
            time = moments[handle]["time"]
            fact = facts.get(target.id)
            note = fact.note if fact else None
            action = ProposedAction("create_short", target)
        else:
            start, end = item.get("from"), item.get("to")
            if not (
                isinstance(start, str)
                and isinstance(end, str)
                and _TIME.match(start)
                and _TIME.match(end)
                and start in times
                and end in times
            ):
                continue
            if _seconds(end) <= _seconds(start):
                continue
            time = f"{start}–{end}"
            overlaps = any(min(e, _seconds(end)) - max(s, _seconds(start)) > 0 for s, e in made)
            note = "Overlaps a clip you've already made." if overlaps else None
            action = None
        if not title or time in seen:
            continue
        seen.add(time)
        cards.append(
            IdeaCard(
                {
                    "kind": "idea",
                    "title": title,
                    "time": time,
                    "angle": angle,
                    "why": why,
                    "style": style,
                    "note": note,
                },
                action,
            )
        )
        if len(cards) == MAX_IDEAS:
            break
    return cards


def fallback_cards(context: CopilotContext) -> list[IdeaCard]:
    """Ideas PeakSift can offer on its own: the video's best unused moments."""
    if context.strategy is None:
        return []
    from app.services.strategy import fallback_ideas

    cards = []
    for moment in fallback_ideas(context.strategy):
        handle = context.moment_handles.get(moment.candidate_id)
        target = context.targets.get(handle) if handle else None
        cards.append(
            IdeaCard(idea_card(moment), ProposedAction("create_short", target) if target else None)
        )
    return cards
