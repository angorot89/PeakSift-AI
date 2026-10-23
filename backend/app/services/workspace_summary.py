"""What a creator needs to see about their projects at a glance (V1.5 Home and Overview).

Read-only facts from existing rows — never new state, never a prediction. For one project:
its current source video (the newest upload), the latest transcription and clip detection run of
that video, candidate counts by decision with the top undecided ones, generated clips and shorts
by status with the most recent shorts, Auto Edit plans waiting for review, YouTube uploads, and
whether published shorts have processed analytics. Each summary is a bounded handful of queries.

The frontend turns these facts into the next best action (``lib/workspace-rules.ts``). Every
query is scoped to the project's owner by the caller (the API checks ownership first).
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AutoEditPlan,
    AutoEditStatus,
    CandidateDecision,
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    Project,
    PublishedContent,
    PublishJob,
    Transcription,
    Video,
)

TOP_CANDIDATES = 3
RECENT_SHORTS = 3
HOME_PROJECTS = 6
# Home looks at this many of the newest projects to find the most recently active ones.
HOME_SCAN = 30
HOME_SHORTS = 6
WORKING = {"queued", "preparing", "uploading", "processing", "rendering", "validating",
           "extracting_audio", "transcribing", "preparing_transcript", "analyzing", "ranking",
           "processing_metadata", "uploaded"}  # fmt: skip


def _counts(rows) -> dict[str, int]:
    return {status: count for status, count in rows}


def _short(edit: ClipEdit, title: str) -> dict:
    return {
        "edit_id": edit.id,
        "clip_id": edit.clip_id,
        "clip_title": title,
        "status": edit.status,
        "duration_seconds": edit.duration_seconds,
        "created_at": edit.created_at,
        "updated_at": edit.updated_at,
    }


def project_summary(db: Session, project: Project) -> dict:
    activity: list[datetime] = [project.updated_at]
    video = db.scalar(
        select(Video)
        .where(Video.project_id == project.id)
        .order_by(Video.created_at.desc(), Video.id.desc())
        .limit(1)
    )
    summary: dict = {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at,
        "source": None,
        "transcript": None,
        "detection": None,
        "clips": {"total": 0, "ready": 0, "working": 0, "failed": 0, "latest_ready_id": None},
        "shorts": {"total": 0, "ready": 0, "working": 0, "failed": 0, "recent": []},
        "plans": {"ready": 0, "latest_ready": None},
        "published": {"uploads": 0, "working": 0, "failed": 0, "with_analytics": 0,
                      "last_synced_at": None},
    }  # fmt: skip
    if video is not None:
        activity.append(video.updated_at)
        summary["source"] = {
            "id": video.id,
            "filename": video.original_filename,
            "status": video.status,
            "duration_seconds": video.duration_seconds,
        }
        transcription = db.scalar(
            select(Transcription)
            .where(Transcription.video_id == video.id)
            .order_by(Transcription.created_at.desc())
            .limit(1)
        )
        if transcription is not None:
            activity.append(transcription.updated_at)
            summary["transcript"] = {
                "status": transcription.status,
                "progress_percent": transcription.progress_percent,
            }
        run = db.scalar(
            select(ClipDetectionRun)
            .where(ClipDetectionRun.video_id == video.id)
            .order_by(ClipDetectionRun.created_at.desc())
            .limit(1)
        )
        if run is not None:
            activity.append(run.updated_at)
            decisions = _counts(
                db.execute(
                    select(ClipCandidate.decision, func.count())
                    .where(ClipCandidate.run_id == run.id)
                    .group_by(ClipCandidate.decision)
                ).all()
            )
            top = db.scalars(
                select(ClipCandidate)
                .where(
                    ClipCandidate.run_id == run.id,
                    ClipCandidate.decision != CandidateDecision.DISMISSED,
                )
                .order_by(ClipCandidate.rank)
                .limit(TOP_CANDIDATES)
            ).all()
            summary["detection"] = {
                "run_id": run.id,
                "status": run.status,
                "candidates": sum(decisions.values()),
                "undecided": decisions.get(CandidateDecision.UNDECIDED, 0),
                "saved": decisions.get(CandidateDecision.SAVED, 0),
                "dismissed": decisions.get(CandidateDecision.DISMISSED, 0),
                "top": [
                    {"id": c.id, "rank": c.rank, "title": c.title, "start_time": c.start_time,
                     "end_time": c.end_time, "duration_seconds": c.duration_seconds,
                     "category": c.category, "overall_score": c.overall_score}
                    for c in top
                ],
            }  # fmt: skip
        clip_counts = _counts(
            db.execute(
                select(Clip.status, func.count())
                .where(Clip.video_id == video.id)
                .group_by(Clip.status)
            ).all()
        )
        latest_clip = db.execute(
            select(Clip.id, Clip.updated_at)
            .where(Clip.video_id == video.id, Clip.status == "ready")
            .order_by(Clip.updated_at.desc())
            .limit(1)
        ).first()
        if latest_clip:
            activity.append(latest_clip.updated_at)
        summary["clips"] = {
            "total": sum(clip_counts.values()),
            "ready": clip_counts.get("ready", 0),
            "working": sum(n for s, n in clip_counts.items() if s in WORKING),
            "failed": clip_counts.get("failed", 0),
            "latest_ready_id": latest_clip.id if latest_clip else None,
        }
        edit_counts = _counts(
            db.execute(
                select(ClipEdit.status, func.count())
                .where(ClipEdit.video_id == video.id)
                .group_by(ClipEdit.status)
            ).all()
        )
        recent = db.execute(
            select(ClipEdit, ClipCandidate.title)
            .join(Clip, Clip.id == ClipEdit.clip_id)
            .join(ClipCandidate, ClipCandidate.id == Clip.candidate_id)
            .where(ClipEdit.video_id == video.id)
            .order_by(ClipEdit.updated_at.desc())
            .limit(RECENT_SHORTS)
        ).all()
        activity.extend(edit.updated_at for edit, _ in recent)
        summary["shorts"] = {
            "total": sum(edit_counts.values()),
            "ready": edit_counts.get("ready", 0),
            "working": sum(n for s, n in edit_counts.items() if s in WORKING),
            "failed": edit_counts.get("failed", 0),
            "recent": [_short(edit, title) for edit, title in recent],
        }
        plan = db.execute(
            select(
                AutoEditPlan.id, AutoEditPlan.clip_id, AutoEditPlan.recipe, AutoEditPlan.updated_at
            )
            .join(Clip, Clip.id == AutoEditPlan.clip_id)
            .where(Clip.video_id == video.id, AutoEditPlan.status == AutoEditStatus.READY)
            .order_by(AutoEditPlan.updated_at.desc())
        ).all()
        if plan:
            activity.append(plan[0].updated_at)
        summary["plans"] = {
            "ready": len(plan),
            "latest_ready": {"plan_id": plan[0].id, "clip_id": plan[0].clip_id,
                             "recipe": plan[0].recipe} if plan else None,
        }  # fmt: skip
        jobs = _counts(
            db.execute(
                select(PublishJob.status, func.count())
                .join(ClipEdit, ClipEdit.id == PublishJob.edit_id)
                .where(ClipEdit.video_id == video.id)
                .group_by(PublishJob.status)
            ).all()
        )
        summary["published"]["uploads"] = sum(
            jobs.get(s, 0) for s in ("uploaded", "processing", "published")
        )
        summary["published"]["working"] = sum(
            jobs.get(s, 0) for s in ("queued", "preparing", "uploading")
        )
        summary["published"]["failed"] = sum(jobs.get(s, 0) for s in ("failed", "provider_failed"))
    analytics = db.execute(
        select(
            func.count(PublishedContent.analytics_complete_through),
            func.max(PublishedContent.last_synced_at),
        ).where(PublishedContent.project_id == project.id)
    ).one()
    summary["published"]["with_analytics"] = analytics[0]
    summary["published"]["last_synced_at"] = analytics[1]
    summary["last_activity_at"] = max(a for a in activity if a is not None)
    return summary


def home(db: Session, user_id: uuid.UUID) -> dict:
    """The creator's most recently active projects and their latest finished shorts."""
    projects = db.scalars(
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(Project.created_at.desc())
        .limit(HOME_SCAN)
    ).all()
    summaries = sorted(
        (project_summary(db, project) for project in projects),
        key=lambda s: s["last_activity_at"],
        reverse=True,
    )
    shorts = db.execute(
        select(ClipEdit, ClipCandidate.title, Project.id, Project.name)
        .join(Clip, Clip.id == ClipEdit.clip_id)
        .join(ClipCandidate, ClipCandidate.id == Clip.candidate_id)
        .join(Video, Video.id == ClipEdit.video_id)
        .join(Project, Project.id == Video.project_id)
        .where(Project.user_id == user_id, ClipEdit.status == "ready")
        .order_by(ClipEdit.updated_at.desc())
        .limit(HOME_SHORTS)
    ).all()
    return {
        "projects": summaries[:HOME_PROJECTS],
        "project_count": db.scalar(
            select(func.count()).select_from(Project).where(Project.user_id == user_id)
        ),
        "recent_shorts": [
            {**_short(edit, title), "project_id": project_id, "project_name": name}
            for edit, title, project_id, name in shorts
        ],
    }
