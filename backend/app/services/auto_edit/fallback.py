"""The deterministic Auto Edit planner: a good, conservative edit without a language model.

Used when the local model is offline, slow or malformed (or when the operator chooses it). It
answers the same ``AutoEditProposal`` as any planner, so the server validator treats both the
same way — and the same context always gives the same plan.

The rules, inside the recipe's bounds:

- **Framing:** Smart Reframe when a completed analysis exists at a confidence the recipe
  accepts; otherwise the source geometry decides — a portrait or square source fills the
  frame (center crop loses little), a landscape source keeps the whole picture (blur
  background) so nobody is cut off.
- **Captions:** on whenever the clip has word or phrase timing and text can be drawn, with the
  recipe's default preset and position (the validator picks word or phrase timing).
- **Hook:** the clip candidate's own hook when it is concise enough to fit; never new text.
- **Visuals:** at most one cutaway, and only for a suggestion whose project asset is a
  *strong* match — by what it shows or by its words (``semantic/matching.py``) — and that is
  long enough for the recipe. A *possible* match is never placed.
- **Audio:** the source is kept as is (normalized as usual); music only when the creator chose
  a track for this plan, at the recipe's quietest level with its ducking; no sound effects.

With patterns from the creator's own shorts (V1.4, only when they asked for it), the rules stay
conservative and inside the recipe: a caption style the recipe offers that the creator's shorts
have tended to do better with is preferred; a hook or a cutaway is left out when their shorts
without one have tended to do better. Captions are never turned off and framing never changes
because of a hint (both keep the speaker clear), music is never added, and every hint used is
named in the explanation.

It is a sensible first draft, not a feature demo.
"""

from app.services.auto_edit.contract import (
    AutoEditContext,
    AutoEditProposal,
    PlannerResult,
)
from app.services.clip_edit.hook import MAX_HOOK_CHARS, normalize_hook_text
from app.services.performance.profile import favours

FALLBACK_PROVIDER = "fallback"
FALLBACK_MODEL = "auto_edit_rules_v1"


def geometry_layout(source_orientation: str) -> str:
    """Framing without Smart Reframe: fill a near-vertical source, keep a landscape one whole."""
    return "center_crop" if source_orientation in ("portrait", "square") else "blur_background"


def _layout(context: AutoEditContext) -> tuple[str, str]:
    caps = context.capabilities
    allowed = context.recipe.get("smart_reframe_confidence") or ()
    if caps.smart_reframe and caps.reframe_confidence in allowed:
        return "smart_reframe", "Smart Reframe follows the speaker; framing confidence is good."
    if geometry_layout(context.source_orientation) == "center_crop":
        return "center_crop", "The source is already close to vertical, so it fills the frame."
    reason = (
        "Framing confidence was too low for Smart Reframe, so the whole frame is kept."
        if caps.smart_reframe
        else "Blur background keeps the whole landscape frame, so no one is cut off."
    )
    return "blur_background", reason


def _evidence(hint: dict) -> str:
    return f"{hint['confidence']} evidence"


def _hook(context: AutoEditContext) -> tuple[dict, str]:
    recipe = context.recipe
    text = normalize_hook_text(context.candidate_hook or "")
    style = recipe["hook_styles"][0] if recipe.get("hook_styles") else "headline"
    seconds = float(recipe.get("hook_seconds", 2.0))
    without = favours(context.performance_hints, "hook", "no_hook")
    if without is not None and recipe.get("hook_allowed"):
        return (
            {"enabled": False, "text": "", "style": style, "duration_seconds": seconds},
            "No opening hook: your shorts without one have tended to do better "
            f"({_evidence(without)}).",
        )
    if not recipe.get("hook_allowed") or not context.capabilities.text_overlays:
        return (
            {"enabled": False, "text": "", "style": style, "duration_seconds": seconds},
            "No opening hook for this recipe.",
        )
    if not text or len(text) > MAX_HOOK_CHARS:
        return (
            {"enabled": False, "text": "", "style": style, "duration_seconds": seconds},
            "No concise hook was available for this clip, so none was added.",
        )
    return (
        {"enabled": True, "text": text, "style": style, "duration_seconds": seconds},
        "Uses the clip's own hook from the moment selection.",
    )


def _visuals(context: AutoEditContext) -> tuple[list[dict], str]:
    recipe = context.recipe
    if not context.capabilities.visuals or "cutaway" not in recipe.get("visual_modes", ()):
        return [], "No visuals for this recipe."
    if not recipe.get("max_visuals"):
        return [], "No visuals for this recipe."
    without = favours(context.performance_hints, "visuals", "no_visuals")
    if without is not None:
        return [], (
            "No cutaway: your shorts without added visuals have tended to do better "
            f"({_evidence(without)})."
        )
    assets = {asset.handle: asset for asset in context.visual_assets}
    for option in context.broll:
        if option.end - option.start < float(recipe.get("min_visual_seconds", 0)):
            continue
        for handle in option.strong_matches:
            asset = assets.get(handle)
            if asset is None:
                continue
            if asset.kind == "video" and (asset.duration or 0) < option.end - option.start:
                continue
            return (
                [{"suggestion": option.handle, "asset": handle, "mode": "cutaway"}],
                f"One cutaway where a project visual strongly matches “{option.query}”.",
            )
    if context.broll:
        return [], "No project visual strongly matched a B-roll suggestion, so none was added."
    return [], "There were no B-roll suggestions for this clip."


def _audio(context: AutoEditContext) -> tuple[dict, str]:
    recipe = context.recipe
    levels = recipe.get("music_levels") or []
    ducking = (recipe.get("ducking") or ["medium"])[0]
    if context.music is not None and levels:
        return (
            {"use_music": True, "music_level": levels[0], "ducking": ducking,
             "transition_sounds": False},
            "Your chosen music stays low under the voice, ducked while you speak.",
        )  # fmt: skip
    note = (
        "Original audio, normalized. Music for this recipe is off."
        if context.music is not None
        else "Original audio, normalized. No music was chosen."
    )
    return (
        {"use_music": False, "music_level": levels[0] if levels else "quiet", "ducking": ducking,
         "transition_sounds": False},
        note,
    )  # fmt: skip


def _caption_preset(context: AutoEditContext) -> tuple[str, dict | None]:
    """The recipe's default preset, or one it offers that the creator's shorts favour."""
    presets = context.recipe["caption_presets"]
    for preset in presets:
        hint = favours(context.performance_hints, "caption_style", preset)
        if hint is not None:
            return preset, hint
    return presets[0], None


class FallbackAutoEditPlanner:
    name = FALLBACK_PROVIDER
    model = FALLBACK_MODEL

    def plan(self, context: AutoEditContext) -> PlannerResult:
        recipe = context.recipe
        caps = context.capabilities
        layout, layout_reason = _layout(context)
        captions_on = caps.text_overlays and (caps.word_timing or caps.phrase_timing)
        captions_reason = (
            "Captions follow each spoken word."
            if captions_on and caps.word_timing
            else "Captions follow the transcript phrases."
            if captions_on
            else "No captions: this clip has no transcript timing yet."
        )
        preset, preset_hint = _caption_preset(context)
        if captions_on and preset_hint is not None:
            captions_reason += (
                f" The “{preset}” style is one your shorts have tended to do better with "
                f"({_evidence(preset_hint)})."
            )
        hook, hook_reason = _hook(context)
        visuals, visual_reason = _visuals(context)
        audio, audio_reason = _audio(context)
        proposal = AutoEditProposal.model_validate(
            {
                "layout": {"mode": layout},
                "captions": {
                    "enabled": captions_on,
                    "preset": preset,
                    "position": recipe["caption_positions"][0],
                },
                "hook": hook,
                "visuals": visuals,
                "audio": audio,
                "explanations": {
                    "layout": layout_reason,
                    "captions": captions_reason,
                    "hook": hook_reason,
                    "visuals": visual_reason,
                    "audio": audio_reason,
                },
            }
        )
        return PlannerResult(proposal, self.name, self.model)
