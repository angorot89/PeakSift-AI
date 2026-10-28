"""Answers PeakSift gives itself, and how terse model answers are completed from the data.

**"What should I do next?"** is a workflow question: the next-action engine already knows the
answer, so an English what-next question is answered by PeakSift directly — the step, why, and
its button — the same step Home shows, instantly and without the model. (Other languages go to
the model, which is told to recommend that same step.)

A small model sometimes answers with a bare title ("The Glue Stick Gamble"). When the whole
answer is a moment's title or the next step's title, PeakSift completes it from the context —
the moment's time, ranking and reason, or the step's reason — never with anything new.
"""

import re

from app.services.copilot.context import CopilotContext

WHAT_NEXT = re.compile(
    r"\bwhat\b[^?]{0,40}\b(do|work on|finish)\b[^?]{0,20}\b(next|now|first)\b"
    r"|\bnext step\b|\bwhat now\b|\bwhat'?s next\b|\bwhere (do|should) i (start|begin)\b"
    r"|\bwhich project should i (finish|work on)\b",
    re.IGNORECASE,
)


def asks_what_next(text: str) -> bool:
    return bool(WHAT_NEXT.search(text))


def next_step_answer(context: CopilotContext) -> str | None:
    """PeakSift's own answer to "what next?" from ``next_step`` / ``next_steps``."""
    step = context.view.get("next_step")
    if isinstance(step, dict) and step.get("title"):
        return f"{step['title']}. {step.get('why', '')}".strip()
    steps = context.view.get("next_steps")
    if isinstance(steps, list) and steps:
        first = steps[0]
        answer = f"{first['project']}: {first['title']}. {first.get('why', '')}".strip()
        if len(steps) > 1:
            second = steps[1]
            answer += f" Then {second['project']}: {second['title'].lower()}."
        return answer
    if (context.view.get("creator") or {}).get("project_count") == 0:
        return "Create your first project and upload a long video to start."
    return None


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def complete(message: str, context: CopilotContext) -> str:
    """A bare title becomes a sentence built from the context (never new facts)."""
    said = _norm(message)
    if not said or len(said.split()) > 12:
        return message
    ranked = ((context.view.get("project") or {}).get("moments") or {}).get("ranked") or []
    for item in ranked:
        if _norm(item.get("title") or "") == said:
            why = f" {item['why']}" if item.get("why") else ""
            return (
                f"Start with “{item['title']}” ({item['time']}) — {item['ranking']}.{why}".strip()
            )
    step = context.view.get("next_step")
    if isinstance(step, dict) and _norm(step.get("title") or "") == said:
        return f"{step['title']}. {step.get('why', '')}".strip()
    return message


def ideas_lead(message: str, count: int) -> str:
    """The text above idea cards: the model's first sentence when it is a short lead, otherwise a
    plain one (the cards hold the ideas; a message re-listing them repeats or garbles them)."""
    first = re.split(r"(?<=[.!?])\s", message.strip(), maxsplit=1)[0]
    if (
        12 <= len(first) <= 120
        and not re.search(r"\b1[.)]", first)
        and "idea 1" not in first.lower()
    ):
        return first
    return (
        f"Here {'is 1 Short idea' if count == 1 else f'are {count} Short ideas'} from this video."
    )
