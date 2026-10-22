"""The provenance snapshot: what a published short *was*, as normalized edit features.

Captured once, when the remote video is linked, from immutable sources — the rendered edit's
own configuration snapshot (an edit never changes after it renders), the Auto Edit plan that
was applied to create it (if any) and the clip candidate. It is never rebuilt from later state.

It holds categories, counts and lengths only: no transcript text, hook wording, asset names,
file keys or provider payloads. Older snapshots keep their ``PROVENANCE_VERSION``.
"""

from typing import Any

from app.models import AutoEditPlan, ClipCandidate, ClipEdit

PROVENANCE_VERSION = "provenance_v1"


def _planner(plan: AutoEditPlan) -> str:
    planner = (plan.confidence_summary or {}).get("planner")
    if planner in ("local_ai", "rules"):
        return planner
    return "rules" if plan.planner_provider == "fallback" else "local_ai"


def _semantic_used(plan: AutoEditPlan | None) -> bool | None:
    """Whether Auto Edit placed a visual matched by what it shows. Unknown for manual edits."""
    if plan is None:
        return None
    sections = (plan.explanation_snapshot or {}).get("sections") or {}
    items = (sections.get("visuals") or {}).get("items") or []
    return any(item.get("matched") == "visual" for item in items if isinstance(item, dict))


def build_provenance(
    edit: ClipEdit, plan: AutoEditPlan | None, candidate: ClipCandidate | None
) -> dict[str, Any]:
    config = edit.config or {}
    captions = config.get("captions") or {}
    hook = config.get("hook") or {}
    audio = config.get("audio") or None
    music = (audio or {}).get("music") or None
    elements = ((config.get("visuals") or {}).get("elements")) or []
    modes = [str(e.get("mode")) for e in elements if isinstance(e, dict)]
    hook_on = bool(hook.get("text"))  # the section exists only when a hook is drawn
    return {
        "duration_seconds": round(float(edit.duration_seconds), 2)
        if edit.duration_seconds
        else None,
        "recipe": plan.recipe if plan is not None else "manual",
        "auto_edit": {
            "used": plan is not None,
            "planner": _planner(plan) if plan is not None else None,
        },
        "layout": config.get("layout") or edit.layout,
        "captions": {
            "enabled": bool(captions.get("enabled", edit.captions_enabled)),
            "preset": captions.get("style") or edit.caption_style,
            "position": captions.get("position") or edit.caption_position,
            "timing": edit.caption_timing,
        },
        "hook": {
            "enabled": hook_on,
            "length_chars": len(str(hook.get("text") or "")) if hook_on else 0,
            "duration_seconds": hook.get("duration") if hook_on else None,
            "style": hook.get("style") if hook_on else None,
            "position": hook.get("position") if hook_on else None,
        },
        "visuals": {
            "count": len(modes),
            "cutaways": modes.count("cutaway"),
            "pips": modes.count("pip"),
            "overlays": modes.count("overlay"),
        },
        "audio": {
            "music": music is not None,
            "ducking": music.get("ducking") if music else None,
            "sfx_count": len((audio or {}).get("sfx") or []),
            "normalized": bool((audio or {}).get("normalize", False)),
        },
        "semantic_visuals": {"used": _semantic_used(plan)},
        "candidate": {
            "rank": candidate.rank if candidate is not None else None,
            "score": candidate.overall_score if candidate is not None else None,
            "category": candidate.category if candidate is not None else None,
        },
    }
