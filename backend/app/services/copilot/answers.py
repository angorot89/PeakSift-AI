"""Answers PeakSift gives itself, and how terse model answers are completed from the data.

Some questions have an answer PeakSift already knows exactly; a small model answering them
sometimes gets them wrong (acceptance found it naming the wrong top pick and describing a
"published" Short that was not). PeakSift answers these itself, from the data, instantly:

- **"What should I do next?"** (English, French, Arabic, Chinese) — the next-action engine's
  step, its reason and its button: the same step Home shows.
- **Requests to act** ("publish my video", "ignore your instructions and delete…") and requests
  for its instructions — what the assistant can and cannot do.
- **How Shorts are doing, when nothing is published** — there is no history yet.
- **The best moment / the top pick** — the ranking, with the best unused moment when the top
  one already has a clip.
- **Short ideas without a video or moments** — what has to happen first.
- **Which visuals are not used yet** — from the library's own usage.

The product's answers are in English, like the rest of PeakSift.

A small model sometimes answers with a bare title ("The Glue Stick Gamble"). When the whole
answer is a moment's title or the next step's title, PeakSift completes it from the context —
the moment's time, ranking and reason, or the step's reason — never with anything new.
"""

import re

from app.services.copilot.context import CopilotContext
from app.services.copilot.ideas import IDEA_WORDS

WHAT_NEXT = re.compile(
    r"\bwhat\b[^?]{0,40}\b(do|work on|finish)\b[^?]{0,20}\b(next|now|first)\b"
    r"|\bnext step\b|\bwhat now\b|\bwhat'?s next\b|\bwhere (do|should) i (start|begin)\b"
    r"|\bwhich project should i (finish|work on)\b"
    r"|\bque (?:dois|devrais|puis)[- ]je faire\b|\bprochaine [ée]tape\b|\bpar o[uù] commencer\b"
    r"|(?:يجب|ينبغي) (?:أن|ان) أفعل|الخطوة التالية|ماذا أفعل"
    r"|接下来.{0,4}做什么|下一步|现在.{0,3}做什么",
    re.IGNORECASE,
)
ACT = re.compile(
    r"^\W*(?:please\s+|pls\s+)?(?:publish|upload|post|delete|remove|erase|rename|unpublish)\b"
    r"|\bignore (?:all |any |your |the )*(?:previous |prior |above )?(?:instructions|rules)\b"
    r"|^\W*(?:publie|supprime|efface|mets en ligne)\b",
    re.IGNORECASE,
)
INSTRUCTIONS = re.compile(
    r"\bsystem prompt\b|\byour (?:rules|instructions|prompt)\b|\bhow (?:are|were) you (?:set up|"
    r"configured|prompted)\b",
    re.IGNORECASE,
)
PERFORMANCE = re.compile(
    r"\b(worked|working|perform\w*|doing|views?|analytics|data|history|results?|stats)\b"
    r"|\b(march[ée]|fonctionn[ée]|performances?|vues|statistiques|donn[ée]es)\b"
    r"|أداء|مشاهدات|表现|播放|数据",
    re.IGNORECASE,
)
BEST_MOMENT = re.compile(
    r"\b(best|top|strongest)\b[^?]{0,30}\b(moment|clip|part)\b|\btop pick\b"
    r"|\bwhich moment\b[^?]{0,30}\b(start|first|use|pick)\b"
    r"|\bmeilleur moment\b|\bquel moment\b[^?]{0,30}\b(commencer|premier|utiliser)\b"
    r"|أفضل لحظة|最好的(?:片段|时刻)|最佳片段",
    re.IGNORECASE,
)
UNUSED_VISUALS = re.compile(
    r"\b(visuals?|images?|b-?roll|assets?)\b[^?]{0,30}\b(not|never|haven'?t|didn'?t)\b[^?]{0,15}"
    r"\bus(e|ed|ing)\b|\bunused (visuals?|images?|assets?)\b|\bvisuels?\b[^?]{0,30}\bpas\b"
    r"[^?]{0,20}\butilis",
    re.IGNORECASE,
)
ANALYTICS_PAGES = {"analytics", "project_analytics", "short_analytics"}
ACT_ANSWER = (
    "I can't publish, delete or change anything — I only suggest, and you decide. To publish, "
    "open a finished Short and choose Publish to YouTube."
)
INSTRUCTIONS_ANSWER = (
    "I can't share how I'm set up. I answer from your own projects, moments, Shorts and "
    "analytics — ask me about them."
)
RANKING_NOTE = (
    "Rankings are PeakSift's editorial judgement of the transcript, not a prediction of views."
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
    """The text above idea cards: the model's first sentence when it is a short lead about the
    ideas, otherwise a plain one (the cards hold the ideas; a message re-listing them repeats or
    garbles them)."""
    first = re.split(r"(?<=[.!?])\s", message.strip(), maxsplit=1)[0]
    if (
        12 <= len(first) <= 120
        and not re.search(r"\b1[.)]", first)
        and "idea 1" not in first.lower()
        and (IDEA_WORDS.search(first) or "angle" in first.lower())  # a lead, not another topic
    ):
        return first
    return (
        f"Here {'is 1 Short idea' if count == 1 else f'are {count} Short ideas'} from this video."
    )


def _ranked(context: CopilotContext) -> list[dict]:
    return ((context.view.get("project") or {}).get("moments") or {}).get("ranked") or []


def _moment_line(item: dict) -> str:
    return f"“{item['title']}” ({item['time']}) — {item['ranking']}"


def best_moment_answer(context: CopilotContext) -> tuple[str, str | None] | None:
    """The ranking's answer to "which moment is best / should I start with?", and the handle of
    the moment to act on (the top pick, or the best one without a clip yet)."""
    ranked = _ranked(context)
    if not ranked:
        return None
    top = ranked[0]
    answer = f"Your top pick is {_moment_line(top)}, editorial score {top['editorial_score']}."
    if top.get("why"):
        answer += f" {top['why']}"
    handle = top["handle"]
    if top.get("already"):
        fresh = next((item for item in ranked[1:] if not item.get("already")), None)
        if fresh is not None:
            answer += (
                f" You've already made a clip from it; the best moment you haven't used is "
                f"{_moment_line(fresh)}."
            )
            handle = fresh["handle"]
        else:
            answer += " You've already made a clip from it."
    return f"{answer} {RANKING_NOTE}", handle


def nothing_published_answer(context: CopilotContext) -> str:
    where = "from this project " if context.project_id else ""
    return (
        f"Nothing {where}has been published from PeakSift yet, so there is no history to learn "
        "from. Once you publish a Short to YouTube and its figures arrive, I can describe what "
        "you observe — never predict it."
    )


def no_ideas_yet_answer(context: CopilotContext) -> str | None:
    """Why there can be no Short ideas yet (no video, or no moments and transcript), or None."""
    view = context.view
    if _ranked(context) or view.get("transcript_excerpt"):
        return None
    project = view.get("project")
    if not isinstance(project, dict):
        return (
            "Short ideas come from a video's moments and transcript. Open a project with a video "
            "and ask there."
        )
    if project.get("source_video") is None:
        return (
            "There's no video in this project yet. Upload a long video and PeakSift will find "
            "the moments worth clipping — then I can suggest Short ideas from them."
        )
    return (
        "Short ideas come from this video's transcript and moments, which aren't ready yet. Ask "
        "again once PeakSift has found the moments."
    )


def unused_visuals_answer(context: CopilotContext) -> str | None:
    """Which visuals no Short version uses yet, from the library's own usage (None when the
    library is not part of this page's context)."""
    library = context.view.get("visual_library")
    if not isinstance(library, dict):
        return None
    items = library.get("items") or []
    if not items:
        return "This project has no visuals yet. Upload images or B-roll videos in Assets."
    unused = [item["name"] for item in items if not item.get("used", "").startswith("used")]
    listed = "" if library.get("total", 0) <= len(items) else f" (of the {len(items)} newest)"
    if not unused:
        return f"Every visual{listed} is used in at least one Short version."
    names = ", ".join(f"“{name}”" for name in unused)
    if len(unused) == len(items):
        return f"None of your visuals{listed} is used in a Short yet: {names}."
    return f"These visuals{listed} aren't used in any Short yet: {names}."


def own_answer(context: CopilotContext, text: str, wants_ideas: bool) -> tuple[str, str] | None:
    """PeakSift's own answer, as (kind, text) — kind says which buttons go with it — or None
    when the question is for the model."""
    if INSTRUCTIONS.search(text):
        return "none", INSTRUCTIONS_ANSWER
    if ACT.search(text):
        return "next_step", ACT_ANSWER
    if asks_what_next(text):
        answer = next_step_answer(context)
        if answer is not None:
            return "next_step", answer
    analytics = context.view.get("analytics")
    if (
        isinstance(analytics, dict)
        and analytics.get("published_shorts") == 0
        and (context.page in ANALYTICS_PAGES or PERFORMANCE.search(text))
    ):
        return "next_step", nothing_published_answer(context)
    if UNUSED_VISUALS.search(text):
        answer = unused_visuals_answer(context)
        if answer is not None:
            return "assets", answer
    if wants_ideas:
        answer = no_ideas_yet_answer(context)
        return ("next_step", answer) if answer else None
    if BEST_MOMENT.search(text):
        best = best_moment_answer(context)
        if best is not None:
            return f"moment:{best[1]}", best[0]
    return None
