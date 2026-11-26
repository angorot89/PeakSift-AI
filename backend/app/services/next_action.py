"""The next best action for a project — one deterministic source of truth (V1.6).

Home's *Continue working*, the project Overview and the Copilot's "What should I do next?" all
read this. The rules look only at a project's real state (``workspace_summary.project_summary``)
and pick one step in the order a creator needs: problems first, then work in progress, then the
next creative step. No model decides the workflow; the Copilot may explain the step, never
change it.

Each step also names the Copilot action that opens it (``action``: type + target kind and id),
so the assistant's button and the dashboard's button lead to the same page.
"""

from dataclasses import dataclass, field
from typing import Any

from app.services import routes

WORKING = {
    "queued",
    "uploaded",
    "processing_metadata",
    "extracting_audio",
    "transcribing",
    "preparing_transcript",
    "analyzing",
    "validating",
    "ranking",
    "rendering",
}
TONE_ORDER = {"attention": 0, "action": 1, "waiting": 2, "done": 3}
CONTINUE_LIMIT = 4


@dataclass(frozen=True)
class NextAction:
    key: str
    title: str
    description: str
    href: str
    tone: str  # attention | action | waiting | done
    cta: str | None = None
    # The matching Copilot action: {"type", "kind", "id"} (kind/id of its target).
    action: dict[str, Any] = field(default_factory=dict)

    def read(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "cta": self.cta,
            "href": self.href,
            "tone": self.tone,
        }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def next_action(p: dict[str, Any]) -> NextAction:
    """The single most useful next step for one project summary."""
    pid = p["id"]
    project = {"type": "open_source", "kind": "project", "id": pid}
    source = p.get("source")
    if source is None:
        return NextAction(
            "upload",
            "Add your long video",
            "Upload a recording, stream, podcast or interview to start.",
            routes.project(pid, "source"),
            "action",
            "Upload a video",
            project,
        )
    if source["status"] == "failed":
        return NextAction(
            "source-failed",
            "This file couldn't be read as a video",
            "Upload a different export (MP4, MOV or WebM).",
            routes.project(pid, "source"),
            "attention",
            "Upload a different file",
            project,
        )
    if source["status"] != "ready":
        return NextAction(
            "source-working",
            "Preparing your video",
            "Reading the file. This usually takes a moment.",
            routes.project(pid, "source"),
            "waiting",
            None,
            project,
        )
    t = p.get("transcript")
    if t is None:
        return NextAction(
            "transcribe",
            "Transcribe your video",
            "PeakSift needs the words to find the best moments.",
            routes.project(pid, "source"),
            "action",
            "Start transcription",
            project,
        )
    if t["status"] == "failed":
        return NextAction(
            "transcript-failed",
            "Transcription needs attention",
            "It stopped before finishing. You can try again.",
            routes.project(pid, "source"),
            "attention",
            "Review and retry",
            project,
        )
    if t["status"] != "completed":
        return NextAction(
            "transcribing",
            "Transcribing your video",
            # Quick start: detection follows by itself (clip_detection/autostart.py).
            "PeakSift finds your moments as soon as the words are ready. You can leave this page."
            if t.get("auto_find_moments")
            else "You can leave this page; it keeps going.",
            routes.project(pid, "source"),
            "waiting",
            None,
            project,
        )

    # A draft or a Short waiting for the creator comes before finding more moments. A draft is
    # the next step only until the project has a Short: drafts used in the editor stay "ready".
    plan = p["plans"]["latest_ready"]
    if plan and p["shorts"]["total"] == 0:
        return NextAction(
            "plan-ready",
            "Your Auto Edit draft is ready",
            "See what PeakSift chose, then use it or adjust it.",
            routes.auto_edit(pid, plan["clip_id"]),
            "action",
            "Review the draft",
            {"type": "open_auto_edit", "kind": "clip", "id": plan["clip_id"]},
        )
    recent = p["shorts"]["recent"]
    rendering = next((s for s in recent if s["status"] in WORKING), None)
    ready = next((s for s in recent if s["status"] == "ready"), None)
    failed = recent[0] if recent and recent[0]["status"] == "failed" else None
    if failed:
        return NextAction(
            "short-failed",
            "A Short needs attention",
            f"“{failed['clip_title']}” didn't finish rendering.",
            routes.editor(pid, failed["clip_id"]),
            "attention",
            "Open the editor",
            {"type": "open_editor", "kind": "clip", "id": failed["clip_id"]},
        )
    if rendering:
        return NextAction(
            "rendering",
            "Rendering your Short",
            f"“{rendering['clip_title']}” will be ready soon.",
            routes.editor(pid, rendering["clip_id"]),
            "waiting",
            None,
            {"type": "open_editor", "kind": "clip", "id": rendering["clip_id"]},
        )
    published_n = p["published"]
    published = published_n["uploads"] > 0 or published_n["with_analytics"] > 0
    short_step = (
        {"type": "open_short", "kind": "short", "id": ready["edit_id"]} if ready else project
    )
    if ready and not published and published_n["working"] == 0 and published_n["failed"] > 0:
        return NextAction(
            "upload-failed",
            "A YouTube upload needs attention",
            "Open the Short to see what happened and try again.",
            routes.short(ready["edit_id"]),
            "attention",
            "Open the Short",
            short_step,
        )
    if published_n["working"] > 0:
        href = routes.short(ready["edit_id"]) if ready else routes.project(pid, "clips")
        return NextAction(
            "uploading",
            "Uploading to YouTube",
            "You can leave this page; it keeps going.",
            href,
            "waiting",
            None,
            short_step if ready else {**project, "type": "open_moments"},
        )
    if ready and not published:
        return NextAction(
            "short-ready",
            "Your Short is ready",
            "Publish it to YouTube or download it.",
            routes.short(ready["edit_id"]),
            "action",
            "Publish or download",
            short_step,
        )
    if published:
        with_figures = published_n["with_analytics"] > 0
        return NextAction(
            "published",
            "See how your Shorts are doing" if with_figures else "Your Short is on YouTube",
            "Views, engagement and what seems to be working."
            if with_figures
            else "Figures appear once YouTube has processed them (2–3 days).",
            routes.project(pid, "analytics"),
            "done",
            "View performance",
            {**project, "type": "open_project_analytics"},
        )
    clips = p["clips"]
    moments = {**project, "type": "open_moments"}
    if clips["latest_ready_id"]:
        return NextAction(
            "create-short",
            "Make your clip a Short",
            "Auto Edit prepares framing, captions, visuals and sound; you can change everything.",
            routes.create(pid, clips["latest_ready_id"]),
            "action",
            "Create Short",
            {"type": "open_create", "kind": "clip", "id": clips["latest_ready_id"]},
        )
    if clips["working"] > 0:
        return NextAction(
            "clip-working",
            "Preparing your clip",
            "Cutting the moment from your video.",
            routes.project(pid, "clips"),
            "waiting",
            None,
            moments,
        )
    d = p.get("detection")
    if d is None:
        return NextAction(
            "find-clips",
            "Find the best moments",
            "PeakSift reads the transcript and ranks moments worth clipping.",
            routes.project(pid, "clips"),
            "action",
            "Find moments",
            moments,
        )
    if d["status"] == "failed":
        return NextAction(
            "detection-failed",
            "Finding moments needs attention",
            "It stopped before finishing. You can try again.",
            routes.project(pid, "clips"),
            "attention",
            "Review and retry",
            moments,
        )
    if d["status"] != "completed":
        return NextAction(
            "finding",
            "Finding the best moments",
            "Reading the transcript and ranking moments.",
            routes.project(pid, "clips"),
            "waiting",
            None,
            moments,
        )
    if d["candidates"] == 0:
        return NextAction(
            "no-moments",
            "No moments stood out",
            "Try again, or with another model if one is available.",
            routes.project(pid, "clips"),
            "attention",
            "Try again",
            moments,
        )
    top = d["top"][0] if d.get("top") else None
    return NextAction(
        "review-clips",
        f"{_plural(d['undecided'], 'moment')} ready to review"
        if d["undecided"] > 0
        else "Pick a moment to make into a Short",
        "Preview the moments PeakSift found and choose one.",
        routes.project(pid, "clips"),
        "action",
        "Review moments",
        {"type": "create_short", "kind": "moment", "id": top["id"]} if top else moments,
    )


def continue_items(projects: list[dict[str, Any]], limit: int = CONTINUE_LIMIT) -> list[dict]:
    """Home's *Continue working*: each project's next step, problems first, then the most
    recently active."""
    items = [(next_action(p), p) for p in projects]
    items.sort(
        key=lambda pair: (TONE_ORDER[pair[0].tone], -pair[1]["last_activity_at"].timestamp())
    )
    return [
        {**step.read(), "project_id": p["id"], "project_name": p["name"]}
        for step, p in items[:limit]
    ]
