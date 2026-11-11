"""Copilot actions: an explicit registry of what an answer may offer the creator to click.

The model can only *propose* an action — an allow-listed type and a handle from its context
(``contract.ACTION_TYPES``). PeakSift then:

1. **checks it now** (``offer``): the target must still exist, belong to the creator and be in a
   state where the step makes sense — a moment that has no clip yet is offered as *Create
   Short*, a dismissed moment is not offered at all, the editor needs a ready clip;
2. **writes the label** itself (the model never writes button text);
3. **checks it again on click** (``resolve``): an answer is history, the project is not. A
   deleted Short, a dismissed moment or a project that is gone gives a plain "no longer
   available" message instead of a broken page.

Every action is navigation, or *Create Short* — the product's own non-destructive first step,
run by the frontend through the existing clip API so its validation and rate limits apply.
No action publishes, deletes, disconnects, renders or changes settings.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AutoEditPlan,
    CandidateDecision,
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    Project,
    PublishedContent,
    ShortTemplate,
    User,
    Video,
)
from app.services import routes
from app.services.copilot.context import CopilotContext, Target, short_text
from app.services.copilot.contract import ProposedAction

GONE = {
    "project": "This project is no longer available.",
    "moment": "This moment is no longer available.",
    "clip": "This clip is no longer available.",
    "short": "This Short is no longer available.",
    "draft": "This Auto Edit draft is no longer available.",
    "published": "This published Short is no longer available.",
    "template": "This template is no longer available.",
}
NOT_READY = "This clip isn't ready yet. Try again in a moment."

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
    "open_brand_studio": "Open Brand Studio",
    "open_template": "Open the template",
    # Offered by PeakSift only (never proposed by the model): Auto Edit for this clip with a
    # template; the clip travels in the action's ``query``, checked again when clicked.
    "use_template": "Use this template",
}


class ActionUnavailable(Exception):
    """The action's target is gone or not in a usable state; ``str()`` is creator-facing."""


@dataclass(frozen=True)
class Resolution:
    kind: str  # "navigate", or "create_short" (the frontend creates the clip, then navigates)
    href: str | None = None
    project_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None


# --- current state, owner-scoped --------------------------------------------------------------


def _project(db: Session, user: User, project_id) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise ActionUnavailable(GONE["project"])
    return project


def _moment(db: Session, user: User, candidate_id) -> tuple[ClipCandidate, Video, Clip | None]:
    row = db.execute(
        select(ClipCandidate, Video)
        .join(ClipDetectionRun, ClipDetectionRun.id == ClipCandidate.run_id)
        .join(Video, Video.id == ClipDetectionRun.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(ClipCandidate.id == candidate_id, Project.user_id == user.id)
    ).first()
    if row is None or row[0].decision == CandidateDecision.DISMISSED:
        raise ActionUnavailable(GONE["moment"])
    clip = db.scalar(select(Clip).where(Clip.candidate_id == candidate_id))
    return row[0], row[1], clip


def _clip(db: Session, user: User, clip_id) -> tuple[Clip, uuid.UUID]:
    row = db.execute(
        select(Clip, Video.project_id)
        .join(Video, Video.id == Clip.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(Clip.id == clip_id, Project.user_id == user.id)
    ).first()
    if row is None:
        raise ActionUnavailable(GONE["clip"])
    return row[0], row[1]


def _short(db: Session, user: User, edit_id) -> tuple[ClipEdit, uuid.UUID]:
    row = db.execute(
        select(ClipEdit, Video.project_id)
        .join(Video, Video.id == ClipEdit.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(ClipEdit.id == edit_id, Project.user_id == user.id)
    ).first()
    if row is None:
        raise ActionUnavailable(GONE["short"])
    return row[0], row[1]


def _draft(db: Session, user: User, plan_id) -> tuple[AutoEditPlan, uuid.UUID]:
    row = db.execute(
        select(AutoEditPlan, Video.project_id)
        .join(Clip, Clip.id == AutoEditPlan.clip_id)
        .join(Video, Video.id == Clip.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(AutoEditPlan.id == plan_id, Project.user_id == user.id)
    ).first()
    if row is None:
        raise ActionUnavailable(GONE["draft"])
    return row[0], row[1]


# --- resolving one action ---------------------------------------------------------------------


def _template(db: Session, user: User, template_id) -> ShortTemplate:
    template = db.scalar(
        select(ShortTemplate).where(
            ShortTemplate.id == template_id, ShortTemplate.user_id == user.id
        )
    )
    if template is None:
        raise ActionUnavailable(GONE["template"])
    return template


def _uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def resolve_action(
    db: Session,
    user: User,
    kind: str,
    target_kind: str | None,
    target_id,
    project_id,
    query: str | None = None,
) -> Resolution:
    """Where an action leads right now — or ``ActionUnavailable`` with a creator-facing reason."""
    target_id, project_id = _uuid(target_id), _uuid(project_id)
    if kind == "open_home":
        return Resolution("navigate", routes.home())
    if kind == "open_brand_studio":
        return Resolution("navigate", routes.brand_studio())
    if target_kind == "template":
        template = _template(db, user, target_id)
        if kind == "use_template":
            clip, owner = _clip(db, user, _uuid(query))
            if clip.status != "ready":
                raise ActionUnavailable(NOT_READY)
            return Resolution(
                "navigate", f"{routes.auto_edit(owner, clip.id)}?new=1&template={template.id}"
            )
        return Resolution("navigate", routes.template(template.id))
    if kind == "new_project":
        return Resolution("navigate", routes.new_project())
    if kind == "open_analytics":
        return Resolution("navigate", routes.analytics())
    if kind == "open_published":
        content = db.scalar(
            select(PublishedContent).where(
                PublishedContent.id == target_id, PublishedContent.user_id == user.id
            )
        )
        if content is None:
            raise ActionUnavailable(GONE["published"])
        return Resolution("navigate", routes.analytics(content.id))
    if target_kind == "project":
        project = _project(db, user, target_id)
        section = {
            "open_project": "",
            "open_source": "source",
            "open_moments": "clips",
            "open_assets": "assets",
            "open_project_analytics": "analytics",
        }
        if kind == "search_assets":
            return Resolution("navigate", routes.assets_search(project.id, query or ""))
        if kind in section:
            return Resolution("navigate", routes.project(project.id, section[kind]))
    if target_kind == "moment":
        candidate, video, clip = _moment(db, user, target_id)
        if clip is None:
            # No clip yet: the only sensible step is to make one (Create Short).
            return Resolution(
                "create_short",
                project_id=video.project_id,
                video_id=video.id,
                run_id=candidate.run_id,
                candidate_id=candidate.id,
            )
        return _clip_step(kind, clip, video.project_id)
    if target_kind == "clip":
        clip, owner = _clip(db, user, target_id)
        return _clip_step(kind, clip, owner)
    if target_kind == "draft":
        plan, owner = _draft(db, user, target_id)
        return Resolution("navigate", routes.auto_edit(owner, plan.clip_id))
    if target_kind == "short":
        edit, owner = _short(db, user, target_id)
        return Resolution("navigate", routes.short(edit.id))
    raise ActionUnavailable("This step isn't available.")


def _clip_step(kind: str, clip: Clip, project_id: uuid.UUID) -> Resolution:
    if kind in ("create_short", "open_create"):
        return Resolution("navigate", routes.create(project_id, clip.id))
    if clip.status != "ready":
        return Resolution("navigate", routes.create(project_id, clip.id))  # shows its progress
    if kind == "open_auto_edit":
        return Resolution("navigate", routes.auto_edit(project_id, clip.id))
    return Resolution("navigate", routes.editor(project_id, clip.id))


# --- offering ---------------------------------------------------------------------------------


def label_for(kind: str, target: Target | None, query: str | None) -> str:
    if kind == "search_assets" and query:
        return f"Search visuals for “{short_text(query, 40)}”"
    if kind == "open_project" and target is not None:
        return f"Open {short_text(target.label, 40)}"
    if kind in ("open_template", "use_template") and target is not None:
        name = target.label.split(": ", 1)[-1]
        return f"{'Use' if kind == 'use_template' else 'Open'} “{short_text(name, 36)}”"
    return LABELS[kind]


def record(kind: str, label: str, target: Target | None, query: str | None) -> dict:
    return {
        "type": kind,
        "label": label,
        "query": query,
        "target": None
        if target is None
        else {
            "kind": target.kind,
            "id": str(target.id) if target.id else None,
            "project": str(target.ref["project"]) if "project" in target.ref else None,
            "label": target.label,
        },
    }


def offer(db: Session, user: User, proposals: list[ProposedAction]) -> list[dict]:
    """The proposals that make sense right now, with PeakSift's labels. A step that needs a
    clip on a moment without one becomes *Create Short*; anything unavailable is left out."""
    offered: list[dict] = []
    for action in proposals:
        target = action.target
        kind = action.type
        if (
            target is not None
            and target.kind == "moment"
            and kind in ("open_create", "open_auto_edit", "open_editor")
            and "clip" not in target.ref
        ):
            kind = "create_short"
        try:
            resolve_action(
                db,
                user,
                kind,
                target.kind if target else None,
                target.id if target else None,
                target.ref.get("project") if target else None,
                action.query,
            )
        except ActionUnavailable:
            continue
        offered.append(record(kind, label_for(kind, target, action.query), target, action.query))
    # Two buttons must never read the same: name the object when labels repeat.
    seen: dict[str, int] = {}
    for item in offered:
        seen[item["label"]] = seen.get(item["label"], 0) + 1
    for item in offered:
        if seen[item["label"]] > 1 and item["target"]:
            name = item["target"]["label"].split(": ", 1)[-1]
            item["label"] = f"{item['label']}: {short_text(name, 32)}"
    unique: list[dict] = []
    for item in offered:
        if all((i["type"], i["label"]) != (item["type"], item["label"]) for i in unique):
            unique.append(item)
    return unique


def resolve_record(db: Session, user: User, item: dict) -> Resolution:
    target = item.get("target") or {}
    return resolve_action(
        db,
        user,
        item["type"],
        target.get("kind"),
        target.get("id"),
        target.get("project"),
        item.get("query"),
    )


def next_step_actions(db: Session, user: User, context: CopilotContext) -> list[dict]:
    """PeakSift's own next step (``services/next_action.py``) as buttons — offered when the
    local assistant cannot answer, so the creator always has a way forward."""
    proposals = [
        ProposedAction(kind, context.targets[handle])
        for kind, handle in context.next_steps
        if handle in context.targets
    ]
    return offer(db, user, proposals)[:2]
