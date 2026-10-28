"""What the Creator Copilot knows: a bounded, structured summary of the creator's own data.

The Copilot never sees database rows. ``build_context`` reads the creator's projects through
owner-scoped queries and turns them into a compact *view* — plain facts in the creator's words
(titles, states, counts, times) — where every object the assistant may talk about or act on is
named by a **symbolic handle** (``moment_1``, ``short_2``, ``visual_3``…). The handle → object map
(``targets``) stays on the server: the model never receives ids, storage keys, paths, providers,
tokens or credentials, and anything it returns is resolved through that map only.

What is included depends on where the creator is (``page``): the Overview gets the workflow, the
Moments page the ranked moments, the editor the current Short and its visuals, Assets the
visual library, Analytics the observed figures and patterns. Text written by people (transcript
lines, titles, hooks, descriptions) is **data**: it is collected under ``transcript_excerpt`` and
inside objects, and the prompt says so; it is never treated as instructions.

The view is bounded (``MAX_VIEW_CHARS``): long lists are trimmed in a fixed order (transcript,
then catalogues) before anything else. Every figure comes from a stored row; an unknown figure
is left out ("not reported"), never estimated.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.models import (
    AudioAsset,
    AutoEditPlan,
    AutoEditStatus,
    BrollAnalysis,
    CandidateDecision,
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    CreatorInsight,
    InsightSet,
    Project,
    PublishedContent,
    Transcription,
    TranscriptSegment,
    User,
    Video,
    VisualAsset,
)
from app.services.clip_detection.labels import moment_label

PAGES = (
    "home",
    "projects",
    "new_project",
    "overview",
    "source",
    "moments",
    "create",
    "auto_edit",
    "editor",
    "assets",
    "project_analytics",
    "analytics",
    "short_analytics",
    "settings",
)
PROJECT_PAGES = {
    "overview",
    "source",
    "moments",
    "create",
    "auto_edit",
    "editor",
    "assets",
    "project_analytics",
}
CLIP_PAGES = {"create", "auto_edit", "editor"}

PAGE_MEANING = {
    "home": "Home: the creator's projects and what to do next",
    "projects": "the list of the creator's projects",
    "new_project": "creating a new project",
    "overview": "a project's overview: its workflow from source video to published Shorts",
    "source": "a project's source video and transcript",
    "moments": "a project's moments: ranked parts of the video worth clipping",
    "create": "starting a Short from one clip (Auto Edit or the editor)",
    "auto_edit": "Auto Edit: a draft edit of one clip prepared by PeakSift for review",
    "editor": "the Short editor for one clip: framing, captions, opening, visuals, sound",
    "assets": "the project's visual library (the creator's own images and B-roll)",
    "project_analytics": "how this project's published Shorts are doing",
    "analytics": "how the creator's published Shorts are doing, and observed patterns",
    "short_analytics": "how one published Short is doing",
    "settings": "account settings (YouTube connection)",
}

MAX_VIEW_CHARS = 12_000
MAX_PROJECTS = 6
MAX_MOMENTS = {"moments": 8, "overview": 4, "source": 3}
MAX_SHORTS = 4
MAX_VISUALS = {"assets": 16, "editor": 10, "auto_edit": 8, "create": 6}
MAX_TRANSCRIPT_LINES = 40
MAX_LINE_CHARS = 160
MAX_TEXT = 180  # other free text (titles, hooks, rationales, descriptions)
MAX_INSIGHTS = 3
TRANSCRIPT_PAGES = {"overview", "source", "moments"}

STOPWORDS = {
    "a",
    "an",
    "the",
    "do",
    "does",
    "i",
    "my",
    "me",
    "have",
    "has",
    "is",
    "are",
    "any",
    "for",
    "of",
    "to",
    "in",
    "on",
    "this",
    "that",
    "part",
    "section",
    "visual",
    "visuals",
    "image",
    "images",
    "picture",
    "pictures",
    "video",
    "videos",
    "broll",
    "b-roll",
    "useful",
    "good",
    "find",
    "show",
    "what",
    "which",
    "can",
    "you",
    "about",
    "with",
    "there",
    "some",
    "use",
    "could",
    "should",
    "please",
    "it",
    "be",
    "best",
    "where",
    "clip",
    "short",
    # Words about the library itself, not about a picture ("Which visuals am I not using?").
    "not",
    "using",
    "used",
    "unused",
    "yet",
    "all",
    "list",
    "many",
    "how",
    "got",
    "own",
    "library",
    "footage",
    "shorts",
    "clips",
}

# Pages where the strategy notes belong: the project as a whole, its source and its moments.
STRATEGY_PAGES = {"overview", "source", "moments", "project_analytics"}

# Creator words for the model, never internal ids (a small model repeats what it reads).
TIMING_WORDS = {
    "aligned_word": "word-synced",
    "phrase_fallback": "phrase by phrase (not word-synced)",
}


def _kind(category: str) -> str:
    from app.services.strategy import CATEGORY_WORD

    return CATEGORY_WORD.get(category, category.replace("_", " "))


class ContextNotFound(Exception):
    """The project or clip does not exist or belongs to someone else (the API answers 404)."""


@dataclass(frozen=True)
class Target:
    """What a handle stands for, on the server only. ``ref`` holds the ids routes need."""

    kind: str  # project, moment, clip, short, draft, visual, published, insight, analytics…
    id: uuid.UUID | None
    label: str  # creator-facing chip text, never an id
    ref: dict[str, uuid.UUID] = field(default_factory=dict)


@dataclass
class CopilotContext:
    page: str
    project_id: uuid.UUID | None
    view: dict[str, Any]
    targets: dict[str, Target]
    scope_label: str
    facts: list[str]
    # PeakSift's own next steps (next-action engine) as (action type, handle) pairs.
    next_steps: list[tuple[str, str]] = field(default_factory=list)
    # Content strategy facts for this project (notes, moments already used), and the handle of
    # every ranked moment by candidate id (idea cards and their actions).
    strategy: Any = None
    moment_handles: dict[uuid.UUID, str] = field(default_factory=dict)

    def view_json(self) -> str:
        return json.dumps(self.view, ensure_ascii=False, separators=(",", ":"), default=str)


# --- helpers ---------------------------------------------------------------------------------


def clock(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = max(0, int(round(seconds)))
    return f"{total // 60}:{total % 60:02d}"


def short_text(text: str | None, limit: int = MAX_TEXT) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def question_topic(question: str) -> str:
    """The words of a question that could describe a picture ("Do I have a visual for the
    bridge section?" → "bridge"). Empty when nothing descriptive is left."""
    words = re.findall(r"[\w'-]+", question.lower())
    kept = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return " ".join(kept[:5])


class _Handles:
    def __init__(self) -> None:
        self.targets: dict[str, Target] = {}
        self._counts: dict[str, int] = {}

    def add(self, prefix: str, target: Target) -> str:
        for handle, existing in self.targets.items():
            if existing.kind == target.kind and existing.id == target.id and target.id:
                return handle
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        handle = f"{prefix}_{self._counts[prefix]}"
        self.targets[handle] = target
        return handle

    def fixed(self, handle: str, target: Target) -> str:
        self.targets[handle] = target
        return handle


# --- the builder -----------------------------------------------------------------------------


def build_context(
    db: Session,
    user: User,
    settings: Settings,
    *,
    page: str,
    project_id: uuid.UUID | None = None,
    clip_id: uuid.UUID | None = None,
    edit_id: uuid.UUID | None = None,
    question: str = "",
) -> CopilotContext:
    """The bounded view for one question on one page. Raises ``ContextNotFound`` for a project,
    clip or Short the creator does not own (the caller answers 404, revealing nothing)."""
    if page not in PAGES:
        page = "home"
    handles = _Handles()
    view: dict[str, Any] = {"page": page, "page_meaning": PAGE_MEANING[page]}
    facts: list[str] = []

    project = None
    if project_id is not None:
        project = db.scalar(
            select(Project).where(Project.id == project_id, Project.user_id == user.id)
        )
        if project is None:
            raise ContextNotFound("project")
    elif page in PROJECT_PAGES:
        page = view["page"] = "home"
        view["page_meaning"] = PAGE_MEANING["home"]

    next_steps: list[tuple[str, str]] = []
    strategy, moment_handles = None, {}
    if project is None:
        view["creator"] = _workspace(db, user, handles)
        view["next_steps"] = _workspace_steps(db, user, handles, next_steps)
        n = view["creator"]["project_count"]
        facts.append(f"{n} project{'s' if n != 1 else ''}" if n else "No projects yet")
        scope = "Your workspace"
    else:
        handles.fixed(
            "project", Target("project", project.id, project.name, {"project": project.id})
        )
        view["project"] = _project(db, project, page, handles, facts)
        view["next_step"] = _project_step(db, project, handles, next_steps)
        strategy, moment_handles = _strategy(db, project, page, view, handles, settings)
        scope = project.name
        clip = None
        if page in CLIP_PAGES and clip_id is not None:
            clip = _owned_clip(db, project, clip_id)
            view["current"] = _current(db, project, clip, edit_id, page, handles, settings, facts)
        if page in TRANSCRIPT_PAGES or clip is not None:
            excerpt = _transcript(db, project, clip)
            if excerpt:
                view["transcript_excerpt"] = excerpt
        if page in {"assets", "editor", "auto_edit", "create"}:
            view["visual_library"] = _visuals(db, project, page, handles, settings, question)
            facts.append(_count(view["visual_library"]["total"], "visual"))

    if page in {"analytics", "project_analytics", "short_analytics", "overview", "home"}:
        view["analytics"] = _analytics(db, user, project, handles, settings)
        if page in {"analytics", "project_analytics", "short_analytics"}:
            facts.append(view["analytics"]["summary"])

    view = _fit(view)
    return CopilotContext(
        page,
        project.id if project else None,
        view,
        handles.targets,
        scope,
        facts[:4],
        next_steps,
        strategy,
        moment_handles,
    )


def _strategy(db, project: Project, page: str, view: dict, handles: _Handles, settings):
    """Strategy notes for the view (on the pages they are about: a small model repeats them
    wherever it sees them); moments already used are marked on their ranked entry."""
    from app.services.strategy import project_strategy

    source = "fake" if settings.performance_provider == "fake" else "youtube"
    strategy = project_strategy(db, project, source)
    moment_handles: dict[uuid.UUID, str] = {}
    for fact in strategy.moments:
        ref = {"project": project.id, "candidate": fact.candidate_id}
        if fact.clip_id:
            ref["clip"] = fact.clip_id
        moment_handles[fact.candidate_id] = handles.add(
            "moment",
            Target("moment", fact.candidate_id, f"Moment: {short_text(fact.title, 48)}", ref),
        )
    by_id = {m.candidate_id: m for m in strategy.moments}
    ranked = ((view.get("project") or {}).get("moments") or {}).get("ranked") or []
    for item in ranked:
        fact = by_id.get(handles.targets[item["handle"]].id)
        if fact is not None and fact.note:
            item["already"] = fact.note
    if page in STRATEGY_PAGES:
        view["strategy"] = {"notes": strategy.notes}
    return strategy, moment_handles


# --- PeakSift's own next step (services/next_action.py) ---------------------------------------


def _step_target(db: Session, project: Project, action: dict) -> tuple[str, Target] | None:
    """The handle prefix and target of a next-action step (``{"type", "kind", "id"}``)."""
    kind, target_id = action.get("kind"), action.get("id")
    ref = {"project": project.id}
    if kind == "project":
        return "project", Target("project", project.id, project.name, ref)
    if kind == "clip":
        clip = db.get(Clip, target_id)
        if clip is None:
            return None
        title = db.scalar(select(ClipCandidate.title).where(ClipCandidate.id == clip.candidate_id))
        return "clip", Target(
            "clip", clip.id, f"Clip: {short_text(title, 48)}", {**ref, "clip": clip.id}
        )
    if kind == "short":
        edit = db.get(ClipEdit, target_id)
        if edit is None:
            return None
        title = db.scalar(
            select(ClipCandidate.title)
            .join(Clip, Clip.candidate_id == ClipCandidate.id)
            .where(Clip.id == edit.clip_id)
        )
        return "short", Target(
            "short",
            edit.id,
            f"Short: {short_text(title, 48)}",
            {**ref, "clip": edit.clip_id, "edit": edit.id},
        )
    if kind == "moment":
        candidate = db.get(ClipCandidate, target_id)
        if candidate is None:
            return None
        clip = db.scalar(select(Clip).where(Clip.candidate_id == candidate.id))
        moment_ref = {**ref, "candidate": candidate.id}
        if clip is not None:
            moment_ref["clip"] = clip.id
        return "moment", Target(
            "moment", candidate.id, f"Moment: {short_text(candidate.title, 48)}", moment_ref
        )
    return None


def _step_view(db, project: Project, handles: _Handles, steps: list, *, workspace: bool):
    from app.services.next_action import next_action
    from app.services.workspace_summary import project_summary

    step = next_action(project_summary(db, project))
    found = _step_target(db, project, step.action)
    item: dict[str, Any] = {"title": step.title, "why": step.description, "state": step.tone}
    if found is not None:
        prefix, target = found
        if prefix == "project" and not workspace:
            handle = "project"
        else:
            handle = handles.add(prefix, target)
        item["action"] = {"type": step.action["type"], "handle": handle}
        steps.append((step.action["type"], handle))
    return item


def _project_step(db, project: Project, handles: _Handles, steps: list) -> dict:
    return _step_view(db, project, handles, steps, workspace=False)


def _workspace_steps(db, user: User, handles: _Handles, steps: list) -> list[dict]:
    """The next step of each recent project, problems first (the order Home uses)."""
    from app.services.next_action import TONE_ORDER

    projects = db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.updated_at.desc())
        .limit(3)
    ).all()
    found: list[tuple[dict, list]] = []
    for project in projects:
        handles.add("project", Target("project", project.id, project.name, {"project": project.id}))
        own: list[tuple[str, str]] = []
        item = _step_view(db, project, handles, own, workspace=True)
        found.append(({"project": short_text(project.name, 80), **item}, own))
    found.sort(key=lambda pair: TONE_ORDER.get(pair[0]["state"], 9))
    for _, own in found:
        steps.extend(own)
    return [item for item, _ in found]


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _owned_clip(db: Session, project: Project, clip_id: uuid.UUID) -> Clip:
    clip = db.scalar(
        select(Clip)
        .join(Video, Video.id == Clip.video_id)
        .where(Clip.id == clip_id, Video.project_id == project.id)
    )
    if clip is None:
        raise ContextNotFound("clip")
    return clip


def _workspace(db: Session, user: User, handles: _Handles) -> dict:
    projects = db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.updated_at.desc())
        .limit(MAX_PROJECTS)
    ).all()
    count = db.scalar(select(func.count()).select_from(Project).where(Project.user_id == user.id))
    listed = []
    for project in projects:
        handle = handles.add(
            "project", Target("project", project.id, project.name, {"project": project.id})
        )
        video = _latest_video(db, project)
        listed.append(
            {
                "handle": handle,
                "name": short_text(project.name, 80),
                "source_video": None if video is None else video.status,
            }
        )
    return {"project_count": count or 0, "recent_projects": listed}


def _latest_video(db: Session, project: Project) -> Video | None:
    return db.scalar(
        select(Video)
        .where(Video.project_id == project.id)
        .order_by(Video.created_at.desc(), Video.id.desc())
        .limit(1)
    )


def _project(db: Session, project: Project, page: str, handles: _Handles, facts: list[str]):
    out: dict[str, Any] = {"handle": "project", "name": short_text(project.name, 80)}
    video = _latest_video(db, project)
    if video is None:
        out["source_video"] = None
        facts.append("No source video yet")
        return out
    out["source_video"] = {
        "file": short_text(video.original_filename, 80),
        "state": video.status,
        "duration": clock(video.duration_seconds),
    }
    transcription = db.scalar(
        select(Transcription)
        .where(Transcription.video_id == video.id)
        .order_by(Transcription.created_at.desc())
        .limit(1)
    )
    out["transcript"] = None if transcription is None else {"state": transcription.status}
    run = db.scalar(
        select(ClipDetectionRun)
        .where(ClipDetectionRun.video_id == video.id)
        .order_by(ClipDetectionRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        out["moments"] = None
    else:
        out["moments"] = _moments(db, project, video, run, page, handles)
        if run.status == "completed":
            facts.append(_count(out["moments"]["total"], "moment"))
    out["shorts"] = _shorts(db, project, video, handles)
    if out["shorts"]["total"]:
        facts.append(_count(out["shorts"]["total"], "Short"))
    out["drafts_ready"] = _drafts(db, project, video, handles)
    music = db.scalar(
        select(func.count()).select_from(AudioAsset).where(AudioAsset.project_id == project.id)
    )
    out["audio_tracks"] = music or 0
    return out


def _moments(db: Session, project: Project, video: Video, run, page: str, handles) -> dict:
    counts = dict(
        db.execute(
            select(ClipCandidate.decision, func.count())
            .where(ClipCandidate.run_id == run.id)
            .group_by(ClipCandidate.decision)
        ).all()
    )
    limit = MAX_MOMENTS.get(page, 3)
    candidates = db.scalars(
        select(ClipCandidate)
        .where(
            ClipCandidate.run_id == run.id, ClipCandidate.decision != CandidateDecision.DISMISSED
        )
        .order_by(ClipCandidate.rank)
        .limit(limit)
    ).all()
    clips = (
        {
            c.candidate_id: c
            for c in db.scalars(
                select(Clip).where(Clip.candidate_id.in_([c.id for c in candidates]))
            ).all()
        }
        if candidates
        else {}
    )
    listed = []
    for c in candidates:
        clip = clips.get(c.id)
        ref = {"project": project.id, "video": video.id, "run": run.id, "candidate": c.id}
        if clip is not None:
            ref["clip"] = clip.id
        handle = handles.add(
            "moment", Target("moment", c.id, f"Moment: {short_text(c.title, 48)}", ref)
        )
        item = {
            "handle": handle,
            "ranking": moment_label(c.rank, c.overall_score),
            "rank": c.rank,
            "title": short_text(c.title, 100),
            "time": f"{clock(c.start_time)}–{clock(c.end_time)}",
            "seconds": round(c.duration_seconds, 1),
            "kind": _kind(c.category),
            "editorial_score": c.overall_score,
            "hook": short_text(c.hook),
            "decision": c.decision,
            "clip": None if clip is None else clip.status,
        }
        if page == "moments":
            item["why"] = short_text(c.rationale, 220)
        listed.append(item)
    return {
        "search_state": run.status,
        "total": sum(counts.values()),
        "saved": counts.get(CandidateDecision.SAVED, 0),
        "dismissed": counts.get(CandidateDecision.DISMISSED, 0),
        "ranked": listed,
        "note": "ranking is editorial judgement of the transcript, never a prediction of views",
    }


def _short_summary(edit: ClipEdit) -> dict:
    config = edit.config or {}
    visuals = (config.get("visuals") or {}).get("elements") or []
    audio = config.get("audio") or {}
    return {
        "state": edit.status,
        "layout": str(edit.layout).replace("_", " "),
        "captions": edit.caption_style if edit.captions_enabled else "off",
        "caption_timing": TIMING_WORDS.get(edit.caption_timing) if edit.captions_enabled else None,
        "opening_hook": short_text(edit.hook_text, 60) if edit.hook_enabled else None,
        "visuals": len(visuals),
        "music": bool(audio.get("music")),
        "sound_effects": len(audio.get("sfx") or []),
        "seconds": round(edit.duration_seconds, 1) if edit.duration_seconds else None,
    }


def _shorts(db: Session, project: Project, video: Video, handles: _Handles) -> dict:
    total = db.scalar(
        select(func.count()).select_from(ClipEdit).where(ClipEdit.video_id == video.id)
    )
    recent = db.execute(
        select(ClipEdit, ClipCandidate.title)
        .join(Clip, Clip.id == ClipEdit.clip_id)
        .join(ClipCandidate, ClipCandidate.id == Clip.candidate_id)
        .where(ClipEdit.video_id == video.id)
        .order_by(ClipEdit.updated_at.desc())
        .limit(MAX_SHORTS)
    ).all()
    published = (
        set(
            db.scalars(
                select(PublishedContent.edit_id).where(
                    PublishedContent.edit_id.in_([e.id for e, _ in recent])
                )
            ).all()
        )
        if recent
        else set()
    )
    listed = []
    for edit, title in recent:
        ref = {"project": project.id, "clip": edit.clip_id, "edit": edit.id}
        handle = handles.add(
            "short", Target("short", edit.id, f"Short: {short_text(title, 48)}", ref)
        )
        listed.append(
            {
                "handle": handle,
                "title": short_text(title, 100),
                **_short_summary(edit),
                "published": edit.id in published,
            }
        )
    return {"total": total or 0, "recent": listed}


def _drafts(db: Session, project: Project, video: Video, handles: _Handles) -> list[dict]:
    rows = db.execute(
        select(AutoEditPlan, ClipCandidate.title)
        .join(Clip, Clip.id == AutoEditPlan.clip_id)
        .join(ClipCandidate, ClipCandidate.id == Clip.candidate_id)
        .where(Clip.video_id == video.id, AutoEditPlan.status == AutoEditStatus.READY)
        .order_by(AutoEditPlan.updated_at.desc())
        .limit(2)
    ).all()
    out = []
    for plan, title in rows:
        ref = {"project": project.id, "clip": plan.clip_id, "plan": plan.id}
        handle = handles.add(
            "draft", Target("draft", plan.id, f"Auto Edit draft: {plan.recipe}", ref)
        )
        out.append({"handle": handle, "style": plan.recipe, "clip_title": short_text(title, 80)})
    return out


def _current(db, project, clip: Clip, edit_id, page, handles: _Handles, settings, facts) -> dict:
    candidate = db.get(ClipCandidate, clip.candidate_id)
    ref = {"project": project.id, "clip": clip.id, "video": clip.video_id}
    clip_handle = handles.add(
        "clip", Target("clip", clip.id, f"Clip: {short_text(candidate.title, 48)}", ref)
    )
    current: dict[str, Any] = {
        "clip": {
            "handle": clip_handle,
            "title": short_text(candidate.title, 100),
            "state": clip.status,
            "seconds": round(clip.duration_seconds, 1),
            "ranking": moment_label(candidate.rank, candidate.overall_score),
            "kind": _kind(candidate.category),
        }
    }
    edit = None
    if edit_id is not None:
        edit = db.scalar(
            select(ClipEdit).where(ClipEdit.id == edit_id, ClipEdit.clip_id == clip.id)
        )
    if edit is None:
        edit = db.scalar(
            select(ClipEdit)
            .where(ClipEdit.clip_id == clip.id)
            .order_by(ClipEdit.updated_at.desc())
            .limit(1)
        )
    if edit is not None:
        handle = handles.add(
            "short",
            Target(
                "short",
                edit.id,
                f"Short: {short_text(candidate.title, 48)}",
                {**ref, "edit": edit.id},
            ),
        )
        current["short"] = {"handle": handle, **_short_summary(edit)}
        facts.append("Current Short: " + edit.status)
    else:
        current["short"] = None
    plan = db.scalar(
        select(AutoEditPlan)
        .where(AutoEditPlan.clip_id == clip.id)
        .order_by(AutoEditPlan.created_at.desc())
        .limit(1)
    )
    if plan is not None:
        notes = (plan.explanation_snapshot or {}).get("notes") or []
        current["latest_draft"] = {
            "style": plan.recipe,
            "state": plan.status,
            "notes": [short_text(n, 160) for n in notes[:4]],  # e.g. why no visuals were placed
        }
    analysis = db.scalar(
        select(BrollAnalysis)
        .options(selectinload(BrollAnalysis.suggestions))
        .where(BrollAnalysis.clip_id == clip.id)
        .order_by(BrollAnalysis.created_at.desc())
        .limit(1)
    )
    if analysis is None:
        current["broll_suggestions"] = None
    else:
        suggestions = [s for s in analysis.suggestions if s.status != "dismissed"][:4]
        current["broll_suggestions"] = {
            "state": analysis.status,
            "items": [
                {
                    "time": f"{clock(s.start_time)}–{clock(s.end_time)}",
                    "shows": short_text(s.query, 80),
                    "why": short_text(s.reason, 140),
                }
                for s in suggestions
            ],
        }
    return current


def _transcript(db: Session, project: Project, clip: Clip | None) -> list[dict] | None:
    video = _latest_video(db, project) if clip is None else db.get(Video, clip.video_id)
    if video is None:
        return None
    transcription = db.scalar(
        select(Transcription)
        .where(Transcription.video_id == video.id, Transcription.status == "completed")
        .order_by(Transcription.created_at.desc())
        .limit(1)
    )
    if transcription is None:
        return None
    statement = select(TranscriptSegment).where(
        TranscriptSegment.transcription_id == transcription.id
    )
    if clip is not None:
        statement = statement.where(
            TranscriptSegment.end_time > clip.start_time,
            TranscriptSegment.start_time < clip.end_time,
        )
    segments = db.scalars(
        statement.order_by(TranscriptSegment.start_time).limit(MAX_TRANSCRIPT_LINES)
    ).all()
    return [
        {"time": clock(s.start_time), "text": short_text(s.text, MAX_LINE_CHARS)} for s in segments
    ]


def _used(edits: int) -> str:
    if not edits:
        return "not used in any Short yet"
    return f"used in {edits} Short version{'s' if edits != 1 else ''}"


def _visuals(db, project: Project, page: str, handles: _Handles, settings, question: str) -> dict:
    from app.services.media_deletion import edits_using_visual_asset
    from app.services.semantic.matching import match_queries
    from app.services.semantic.registry import configured_identity
    from app.services.semantic.state import semantic_state

    assets = list(
        db.scalars(
            select(VisualAsset)
            .options(selectinload(VisualAsset.semantic_indexes))
            .where(VisualAsset.project_id == project.id)
            .order_by(VisualAsset.created_at.desc())
        )
    )
    identity = configured_identity(settings)
    states = [semantic_state(a.semantic_indexes, identity).value for a in assets]
    listed = []
    for asset in assets[: MAX_VISUALS.get(page, 6)]:
        handle = handles.add(
            "visual",
            Target(
                "visual",
                asset.id,
                f"Visual: {short_text(asset.display_name, 40)}",
                {"project": project.id, "visual": asset.id},
            ),
        )
        listed.append(
            {
                "handle": handle,
                "name": short_text(asset.display_name, 60),
                "kind": asset.kind,
                "description": short_text(asset.description, 120),
                "tags": [short_text(t, 24) for t in (asset.tags or [])[:6]],
                "used": _used(edits_using_visual_asset(db, asset)),
            }
        )
    out: dict[str, Any] = {
        "total": len(assets),
        "images": sum(a.kind == "image" for a in assets),
        "videos": sum(a.kind == "video" for a in assets),
        "searchable_by_content": states.count("ready"),
        "still_preparing": sum(s in {"not_indexed", "queued", "indexing", "stale"} for s in states),
        "items": listed,
    }
    topic = question_topic(question)
    if topic and assets:
        matches = match_queries(db, project.id, [topic], assets, settings, limit=4).get(topic)
        found = []
        for match in matches:
            handle = handles.add(
                "visual",
                Target(
                    "visual",
                    match.asset.id,
                    f"Visual: {short_text(match.asset.display_name, 40)}",
                    {"project": project.id, "visual": match.asset.id},
                ),
            )
            found.append(
                {
                    "handle": handle,
                    "name": short_text(match.asset.display_name, 60),
                    "match": match.strength.value,
                    "matched_by": match.method.value,
                }
            )
        out["search_for_question"] = {"query": topic, "matches": found}
    return out


def _analytics(db, user: User, project: Project | None, handles: _Handles, settings) -> dict:
    from app.services.performance import summary as perf

    source = "fake" if settings.performance_provider == "fake" else "youtube"
    contents = perf.user_contents(db, user.id)
    if project is not None:
        contents = [c for c in contents if c.project_id == project.id]
    counters = perf.latest_counters(db, [c.id for c in contents])
    processed = perf.processed_totals(db, {i: c.source for i, c in counters.items()})
    analytics_ref = {"project": project.id} if project else {}
    handles.fixed("analytics", Target("analytics", None, "Your analytics", analytics_ref))

    def total(values: list[int | None]) -> int | None:
        known = [v for v in values if v is not None]
        return sum(known) if known else None

    shorts = []
    for content in contents[:5]:
        c = counters.get(content.id)
        p = processed.get(content.id)
        handle = handles.add(
            "published",
            Target(
                "published",
                content.id,
                f"Published: {short_text(content.title, 40)}",
                {"published": content.id},
            ),
        )
        shorts.append(
            {
                "handle": handle,
                "title": short_text(content.title, 80),
                "published": content.published_at.date().isoformat(),
                "views": c.views if c else None,
                "engaged_views": p.engaged_views if p else None,
                "average_percent_viewed": p.average_view_percentage if p else None,
            }
        )
    simulated = any(c.source == "fake" for c in counters.values())
    out: dict[str, Any] = {
        "published_shorts": len(contents),
        "with_figures": sum(1 for c in contents if c.id in counters),
        "total_views": total([counters[c.id].views for c in contents if c.id in counters]),
        "simulated_data": simulated,
        "recent": shorts,
        "note": "observed figures only; never a prediction; null means not reported",
    }
    insight_set = db.scalar(
        select(InsightSet).where(InsightSet.user_id == user.id, InsightSet.source == source)
    )
    if insight_set is None:
        out["patterns"] = {"state": "not computed yet"}
    else:
        from app.services.performance.insights import MIN_SAMPLE

        rows = db.scalars(
            select(CreatorInsight)
            .where(CreatorInsight.set_id == insight_set.id, CreatorInsight.dismissed_at.is_(None))
            .order_by(CreatorInsight.rank)
            .limit(MAX_INSIGHTS)
        ).all()
        listed = []
        for row in rows:
            handle = handles.add("insight", Target("insight", row.id, "Pattern in your Shorts", {}))
            listed.append(
                {"handle": handle, "statement": row.statement, "confidence": row.confidence}
            )
        out["patterns"] = {
            "state": insight_set.status,  # "insufficient": too few comparable Shorts
            "comparable_shorts": insight_set.sample_size,
            "minimum_needed": MIN_SAMPLE,
            "observed": listed,
        }
    n = out["published_shorts"]
    out["summary"] = "Nothing published yet" if n == 0 else f"{_count(n, 'published Short')}"
    return out


def _fit(view: dict[str, Any]) -> dict[str, Any]:
    """Keep the view under ``MAX_VIEW_CHARS``: drop transcript lines from the end first, then
    shorten catalogues — the facts the creator asked about come last."""

    def size() -> int:
        return len(json.dumps(view, ensure_ascii=False, separators=(",", ":"), default=str))

    lines = view.get("transcript_excerpt")
    while lines and size() > MAX_VIEW_CHARS:
        if len(lines) > 4:
            del lines[len(lines) // 2 :]
        else:
            lines.clear()
    if lines is not None and not lines:
        view.pop("transcript_excerpt", None)
    for path in (("visual_library", "items"), ("project", "moments", "ranked")):
        node: Any = view
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
        items = node.get(path[-1]) if isinstance(node, dict) else None
        while items and size() > MAX_VIEW_CHARS:
            items.pop()
    return view
