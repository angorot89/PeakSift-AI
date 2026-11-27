"""The creator's Shorts library: every Short they have made, with one honest status each.

A **Short** is one rendered version of a clip (a ``ClipEdit``): what publishing, analytics and
template/brand provenance attach to. A **draft** is a clip the creator cut from a moment but has
not made a version of yet (``kind == "draft"``, identified by the clip id).

``short_status`` is the only place a creator-level status is derived from domain state; the
frontend maps these keys to words (``lib/shorts-rules.ts``). Statuses:

- ``draft`` — a cut moment with no version yet;
- ``rendering`` — a version (or the moment's cut) is being made;
- ``ready`` — rendered, not on YouTube;
- ``publishing`` — an upload in progress, or YouTube still processing it;
- ``on_youtube`` — uploaded; YouTube has not confirmed it as published (PeakSift's upload-only
  access cannot see processing), so it is never called "published";
- ``published`` — YouTube confirmed it;
- ``failed`` — the render (or the cut) failed;
- ``needs_attention`` — a render or an upload stopped reporting, or an upload failed.

Separately from the status, a Short can be **hidden** by the creator (``hidden_at`` on the version,
or on the clip for a draft) and can have a post **scheduled** for later (a publish job waiting for
its time, which never changes the status: the Short stays "ready" until the post goes out).

Everything is scoped to one creator by the caller's ``user_id``; the whole library is a fixed
handful of queries whatever its size (no per-Short queries). Failed versions of a clip that has
a newer version are history, not something to fix: they are left out of the library and listed
among the newer version's versions.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    AutoEditPlan,
    AutoEditStatus,
    Clip,
    ClipCandidate,
    ClipEdit,
    ClipEditStatus,
    Project,
    PublishedContent,
    PublishJob,
    PublishStatus,
    Video,
)
from app.services.clip_edit.pipeline import is_stale as edit_is_stale
from app.services.clip_render.pipeline import is_stale as clip_is_stale
from app.services.performance import summary
from app.services.publishing.pipeline import awaiting_processing
from app.services.publishing.pipeline import is_stale as job_is_stale

# A creator's library is returned whole (filtering and search happen in the browser); this caps a
# pathological account so one request stays bounded.
LIBRARY_LIMIT = 500
ACTIVE = {"queued", "rendering", "validating"}


class ShortStatus(StrEnum):
    DRAFT = "draft"
    RENDERING = "rendering"
    READY = "ready"
    PUBLISHING = "publishing"
    ON_YOUTUBE = "on_youtube"
    PUBLISHED = "published"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"


class PublishState(StrEnum):
    NOT_PUBLISHED = "not_published"
    PREPARING = "preparing"  # queued or preparing the upload
    UPLOADING = "uploading"
    PROCESSING = "processing"  # uploaded; YouTube's processing is still being checked
    ON_YOUTUBE = "on_youtube"  # uploaded; processing cannot be followed
    PUBLISHED = "published"
    STALLED = "stalled"  # an upload stopped reporting
    FAILED = "failed"  # PeakSift could not upload it, or YouTube rejected it


@dataclass(frozen=True)
class Publication:
    state: PublishState
    job: PublishJob | None


def publication(jobs: list[PublishJob], settings: Settings) -> Publication:
    """What happened on YouTube, from one edit's publish jobs (newest first).

    A video YouTube has (published, then uploaded or processing) outranks a later attempt; with
    none, the newest attempt decides. A post still waiting for its scheduled time has not
    happened yet, so it never decides the state (the Short stays "ready" until it goes out)."""
    jobs = [job for job in jobs if job.status != PublishStatus.SCHEDULED]
    for job in jobs:
        if job.status == PublishStatus.PUBLISHED:
            return Publication(PublishState.PUBLISHED, job)
    for job in jobs:
        if job.status in (PublishStatus.UPLOADED, PublishStatus.PROCESSING):
            processing = awaiting_processing(job, settings)
            return Publication(
                PublishState.PROCESSING if processing else PublishState.ON_YOUTUBE, job
            )
    if not jobs:
        return Publication(PublishState.NOT_PUBLISHED, None)
    latest = jobs[0]
    if latest.status in (PublishStatus.FAILED, PublishStatus.PROVIDER_FAILED):
        return Publication(PublishState.FAILED, latest)
    if job_is_stale(latest, settings):
        return Publication(PublishState.STALLED, latest)
    if latest.status == PublishStatus.UPLOADING:
        return Publication(PublishState.UPLOADING, latest)
    return Publication(PublishState.PREPARING, latest)


def short_status(
    edit: ClipEdit, published: Publication, settings: Settings
) -> tuple[ShortStatus, str | None]:
    """A version's creator-level status and, when it needs the creator, why."""
    if edit.status in ACTIVE:
        if edit_is_stale(edit, settings):
            return ShortStatus.NEEDS_ATTENTION, "render_stalled"
        return ShortStatus.RENDERING, None
    if edit.status != ClipEditStatus.READY:
        return ShortStatus.FAILED, "render_failed"
    match published.state:
        case PublishState.PUBLISHED:
            return ShortStatus.PUBLISHED, None
        case PublishState.ON_YOUTUBE:
            return ShortStatus.ON_YOUTUBE, None
        case PublishState.PREPARING | PublishState.UPLOADING | PublishState.PROCESSING:
            return ShortStatus.PUBLISHING, None
        case PublishState.STALLED:
            return ShortStatus.NEEDS_ATTENTION, "publish_stalled"
        case PublishState.FAILED:
            return ShortStatus.NEEDS_ATTENTION, "publish_failed"
    return ShortStatus.READY, None


def draft_status(clip: Clip, settings: Settings) -> tuple[ShortStatus, str | None]:
    """A cut moment without a version: a draft once the cut is ready."""
    if clip.status in ACTIVE:
        if clip_is_stale(clip, settings):
            return ShortStatus.NEEDS_ATTENTION, "clip_stalled"
        return ShortStatus.RENDERING, None
    if clip.status != "ready":
        return ShortStatus.FAILED, "clip_failed"
    return ShortStatus.DRAFT, None


def _origin(edit: ClipEdit) -> tuple[dict | None, dict | None, bool]:
    """The template and brand a version was made with — recorded with the version, so a later
    template or brand change never rewrites it."""
    origin = edit.origin or {}
    template = origin.get("template") if isinstance(origin.get("template"), dict) else None
    brand = origin.get("brand") if isinstance(origin.get("brand"), dict) else None
    return (
        {"id": template.get("id"), "name": template.get("name"),
         "version": template.get("version")} if template and template.get("name") else None,
        {"name": brand["name"]} if brand and brand.get("name") else None,
        bool(origin.get("auto_edit_plan_id")),
    )  # fmt: skip


def _market(edit: ClipEdit) -> dict | None:
    """The local market a version was made for (V1.8), as recorded with it; None for Global."""
    market = (edit.origin or {}).get("market")
    if not isinstance(market, dict) or not market.get("name") or market.get("code") == "global":
        return None
    return {"code": market.get("code"), "name": market["name"]}


def _publish_read(
    published: Publication, content: PublishedContent | None, settings: Settings
) -> dict[str, Any]:
    job = published.job
    on_youtube = published.state in (
        PublishState.PUBLISHED,
        PublishState.ON_YOUTUBE,
        PublishState.PROCESSING,
    )
    video_id = job.provider_video_id if job else None
    simulated = bool(video_id) and video_id.startswith("fake-")
    return {
        "state": published.state,
        "platform": job.provider if job else None,
        # When YouTube confirmed it, else when the upload finished; never invented.
        "published_at": (job.published_at or (content.published_at if content else None))
        if published.state == PublishState.PUBLISHED and job
        else None,
        "uploaded_at": job.completed_at if on_youtube and job else None,
        "privacy": job.privacy if on_youtube and job else None,
        "simulated": simulated,
        "video_url": f"https://youtu.be/{video_id}" if on_youtube and video_id and not simulated
        else None,
        "job_id": job.id if job else None,
    }  # fmt: skip


def _performance(content: PublishedContent | None, counters) -> dict[str, Any] | None:
    if content is None:
        return None
    return {
        "content_id": content.id,
        "views": counters.views if counters else None,
        "likes": counters.likes if counters else None,
        "comments": counters.comments if counters else None,
        "observed_at": counters.observed_at if counters else None,
        "simulated": counters.source == "fake" if counters else False,
        "analytics_through": content.analytics_complete_through,
    }


@dataclass(frozen=True)
class _Row:
    edit: ClipEdit
    clip: Clip
    title: str
    video_id: uuid.UUID
    filename: str
    project_id: uuid.UUID
    project_name: str
    number: int
    count: int


def _rows(db: Session, user_id: uuid.UUID, *, edit_id: uuid.UUID | None = None) -> list[_Row]:
    """The creator's versions (one, with ``edit_id``) with their clip, moment, source and
    project, and each version's number among its clip's versions."""
    numbered = (
        select(
            ClipEdit.id.label("edit_id"),
            func.row_number()
            .over(partition_by=ClipEdit.clip_id, order_by=(ClipEdit.created_at, ClipEdit.id))
            .label("number"),
            func.count().over(partition_by=ClipEdit.clip_id).label("count"),
            func.max(ClipEdit.created_at).over(partition_by=ClipEdit.clip_id).label("newest"),
        )
        .join(Video, Video.id == ClipEdit.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(Project.user_id == user_id)
        .subquery()
    )
    query = (
        select(ClipEdit, Clip, ClipCandidate.title, Video.id, Video.original_filename, Project.id,
               Project.name, numbered.c.number, numbered.c.count)
        .join(numbered, numbered.c.edit_id == ClipEdit.id)
        .join(Clip, Clip.id == ClipEdit.clip_id)
        .join(ClipCandidate, ClipCandidate.id == Clip.candidate_id)
        .join(Video, Video.id == ClipEdit.video_id)
        .join(Project, Project.id == Video.project_id)
    )  # fmt: skip
    if edit_id is not None:
        query = query.where(ClipEdit.id == edit_id)
    else:  # a failed attempt the creator has since replaced is history, not a Short to fix
        query = query.where(
            (ClipEdit.status != ClipEditStatus.FAILED) | (ClipEdit.created_at >= numbered.c.newest)
        )
    rows = db.execute(
        query.order_by(ClipEdit.updated_at.desc(), ClipEdit.id).limit(LIBRARY_LIMIT)
    ).all()
    return [_Row(*row) for row in rows]


def _jobs(db: Session, edit_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PublishJob]]:
    jobs: dict[uuid.UUID, list[PublishJob]] = {}
    if edit_ids:
        for job in db.scalars(
            select(PublishJob)
            .where(PublishJob.edit_id.in_(edit_ids))
            .order_by(PublishJob.created_at.desc(), PublishJob.id)
        ):
            jobs.setdefault(job.edit_id, []).append(job)
    return jobs


def _contents(db: Session, edit_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PublishedContent]]:
    contents: dict[uuid.UUID, list[PublishedContent]] = {}
    if edit_ids:
        for content in db.scalars(
            select(PublishedContent)
            .where(PublishedContent.edit_id.in_(edit_ids))
            .order_by(PublishedContent.published_at.desc())
        ):
            contents.setdefault(content.edit_id, []).append(content)
    return contents


def _schedule(jobs: list[PublishJob]) -> dict[str, Any] | None:
    """The soonest post still waiting for its time, if any."""
    waiting = [j for j in jobs if j.status == PublishStatus.SCHEDULED and j.scheduled_at]
    if not waiting:
        return None
    soonest = min(waiting, key=lambda job: job.scheduled_at)
    return {"at": soonest.scheduled_at, "platform": soonest.provider}


def _short_items(db: Session, rows: list[_Row], settings: Settings) -> list[dict[str, Any]]:
    ids = [row.edit.id for row in rows]
    jobs = _jobs(db, ids)
    contents = _contents(db, ids)
    items: list[dict[str, Any]] = []
    decided: list[tuple[_Row, Publication, PublishedContent | None]] = []
    for row in rows:
        published = publication(jobs.get(row.edit.id, []), settings)
        candidates = contents.get(row.edit.id, [])
        job_id = published.job.id if published.job else None
        content = next((c for c in candidates if c.publish_job_id == job_id), None)
        if content is None and published.state in (PublishState.PUBLISHED,
                                                    PublishState.ON_YOUTUBE,
                                                    PublishState.PROCESSING):  # fmt: skip
            content = candidates[0] if candidates else None
        decided.append((row, published, content))
    counters = summary.latest_counters(db, [c.id for _, _, c in decided if c is not None])
    for row, published, content in decided:
        edit = row.edit
        status, reason = short_status(edit, published, settings)
        template, brand, auto_edit = _origin(edit)
        ready = edit.status == ClipEditStatus.READY
        updated = max(
            [edit.updated_at] + [j.updated_at for j in jobs.get(edit.id, [])[:1] if j.updated_at]
        )
        items.append({
            "id": edit.id, "kind": "short", "status": status, "reason": reason,
            "title": row.title, "edit_id": edit.id, "clip_id": row.clip.id,
            "project": {"id": row.project_id, "name": row.project_name},
            "source": {"id": row.video_id, "filename": row.filename},
            "duration_seconds": edit.duration_seconds if ready else row.clip.duration_seconds,
            "preview": "short" if ready else ("clip" if row.clip.status == "ready" else None),
            "version": {"number": row.number, "count": row.count},
            "template": template, "brand": brand, "market": _market(edit), "auto_edit": auto_edit,
            "plan_ready": False,
            "publish": _publish_read(published, content, settings),
            "performance": _performance(content, counters.get(content.id) if content else None),
            "created_at": edit.created_at, "updated_at": updated,
            "rendered_at": edit.completed_at if ready else None,
            "hidden": edit.hidden_at is not None, "schedule": _schedule(jobs.get(edit.id, [])),
        })  # fmt: skip
    return items


def _not_published() -> dict[str, Any]:
    return {"state": PublishState.NOT_PUBLISHED, "platform": None, "published_at": None,
            "uploaded_at": None, "privacy": None, "simulated": False, "video_url": None,
            "job_id": None}  # fmt: skip


def _draft_items(
    db: Session, user_id: uuid.UUID, settings: Settings, *, clip_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Clips cut from a moment that have no version yet."""
    query = (
        select(Clip, ClipCandidate.title, Video.id, Video.original_filename, Project.id,
               Project.name)
        .join(ClipCandidate, ClipCandidate.id == Clip.candidate_id)
        .join(Video, Video.id == Clip.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(Project.user_id == user_id, ~exists().where(ClipEdit.clip_id == Clip.id))
    )  # fmt: skip
    if clip_id is not None:
        query = query.where(Clip.id == clip_id)
    rows = db.execute(query.order_by(Clip.updated_at.desc(), Clip.id).limit(LIBRARY_LIMIT)).all()
    planned = set()
    if rows:
        planned = set(
            db.scalars(
                select(AutoEditPlan.clip_id).where(
                    AutoEditPlan.clip_id.in_([clip.id for clip, *_ in rows]),
                    AutoEditPlan.status == AutoEditStatus.READY,
                )
            )
        )
    items = []
    for clip, title, video_id, filename, project_id, project_name in rows:
        status, reason = draft_status(clip, settings)
        items.append({
            "id": clip.id, "kind": "draft", "status": status, "reason": reason, "title": title,
            "edit_id": None, "clip_id": clip.id,
            "project": {"id": project_id, "name": project_name},
            "source": {"id": video_id, "filename": filename},
            "duration_seconds": clip.duration_seconds,
            "preview": "clip" if clip.status == "ready" else None,
            "version": None, "template": None, "brand": None, "auto_edit": False,
            "plan_ready": clip.id in planned, "publish": _not_published(), "performance": None,
            "created_at": clip.created_at, "updated_at": clip.updated_at, "rendered_at": None,
            "hidden": clip.hidden_at is not None, "schedule": None,
        })  # fmt: skip
    return items


def library(db: Session, user_id: uuid.UUID, settings: Settings) -> dict[str, Any]:
    """Every Short and draft of this creator, most recently updated first."""
    items = _short_items(db, _rows(db, user_id), settings) + _draft_items(db, user_id, settings)
    items.sort(key=lambda item: (item["updated_at"], str(item["id"])), reverse=True)
    return {"shorts": items[:LIBRARY_LIMIT], "truncated": len(items) > LIBRARY_LIMIT}


def _versions(db: Session, clip_id: uuid.UUID, settings: Settings) -> list[dict[str, Any]]:
    edits = db.scalars(
        select(ClipEdit)
        .where(ClipEdit.clip_id == clip_id)
        .order_by(ClipEdit.created_at, ClipEdit.id)
    ).all()
    jobs = _jobs(db, [edit.id for edit in edits])
    versions = []
    for number, edit in enumerate(edits, start=1):
        status, _ = short_status(edit, publication(jobs.get(edit.id, []), settings), settings)
        versions.append({"id": edit.id, "number": number, "status": status,
                         "created_at": edit.created_at})  # fmt: skip
    return versions


def _moment(clip: Clip) -> dict[str, Any]:
    candidate = clip.candidate
    return {
        "start_time": clip.start_time,
        "end_time": clip.end_time,
        "rank": candidate.rank,
        "category": candidate.category,
    }


def detail(
    db: Session, user_id: uuid.UUID, short_id: uuid.UUID, settings: Settings
) -> dict[str, Any] | None:
    """One Short (a version id) or draft (a clip id without versions), owner-scoped; a clip id
    whose clip now has versions resolves to its newest version. ``None`` for anything else."""
    rows = _rows(db, user_id, edit_id=short_id)
    if not rows:
        newest = db.scalar(
            select(ClipEdit.id)
            .join(Video, Video.id == ClipEdit.video_id)
            .join(Project, Project.id == Video.project_id)
            .where(ClipEdit.clip_id == short_id, Project.user_id == user_id)
            .order_by(ClipEdit.created_at.desc(), ClipEdit.id.desc())
            .limit(1)
        )
        if newest is not None:
            rows = _rows(db, user_id, edit_id=newest)
    if rows:
        [item] = _short_items(db, rows, settings)
        row = rows[0]
        edit = row.edit
        item["moment"] = _moment(row.clip)
        item["versions"] = _versions(db, row.clip.id, settings)
        item["render"] = {
            "error_message": edit.error_message if edit.status == ClipEditStatus.FAILED else None,
            "file_size": edit.file_size if edit.status == ClipEditStatus.READY else None,
            "progress_percent": edit.progress_percent,
        }
        item["auto_edit_plan_id"] = (edit.origin or {}).get("auto_edit_plan_id")
        return item
    drafts = _draft_items(db, user_id, settings, clip_id=short_id)
    if not drafts:
        return None
    [item] = drafts
    clip = db.get(Clip, short_id)
    item["moment"] = _moment(clip)
    item["versions"] = []
    item["render"] = {
        "error_message": clip.error_message if item["status"] == ShortStatus.FAILED else None,
        "file_size": None,
        "progress_percent": clip.progress_percent,
    }
    item["auto_edit_plan_id"] = db.scalar(
        select(AutoEditPlan.id)
        .where(AutoEditPlan.clip_id == clip.id, AutoEditPlan.status == AutoEditStatus.READY)
        .order_by(AutoEditPlan.updated_at.desc())
        .limit(1)
    )
    return item


def set_hidden(db: Session, user_id: uuid.UUID, short_id: uuid.UUID, hidden: bool) -> bool:
    """Hide or show one of this creator's Shorts (a version id) or drafts (a clip id without
    versions) in the library. ``False`` when there is no such Short for this creator."""
    when = datetime.now(UTC) if hidden else None
    edit = db.scalar(
        select(ClipEdit)
        .join(Video, Video.id == ClipEdit.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(ClipEdit.id == short_id, Project.user_id == user_id)
    )
    if edit is not None:
        edit.hidden_at = when
        db.commit()
        return True
    clip = db.scalar(
        select(Clip)
        .join(Video, Video.id == Clip.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(Clip.id == short_id, Project.user_id == user_id)
    )
    if clip is None:
        return False
    clip.hidden_at = when
    db.commit()
    return True
