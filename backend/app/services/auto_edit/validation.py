"""The authoritative Auto Edit plan validator: a planner proposes, the server decides.

``validate_plan`` turns an untrusted ``AutoEditProposal`` into an ordinary, normalized
``EditConfig`` — the same configuration a creator could build by hand — using only what the
server knows exists (the context's facts and handle maps) and the recipe's bounds. Handles
become ids here and nowhere else; a handle the server did not issue is ignored and counted.

**Degradation policy.** An invalid *optional* choice never sinks the plan: it is replaced by
the safe choice (or left out) and the creator gets a plain note saying so —

- Smart Reframe without a usable analysis → the source geometry decides (blur or crop);
- a caption preset or position outside the recipe → the recipe's default; word timing without
  a completed track → phrase timing; no transcript timing → no captions;
- a hook that is too long, does not fit, is not grounded in the clip (new names, numbers or
  claims) or that the recipe does not allow → the candidate's own hook, or no hook; a style or
  length outside the recipe → the recipe's;
- a visual with an unknown suggestion, an asset that does not match it, a mode or length the
  recipe does not allow, a clash with another visual, or that the asset cannot fill → dropped;
- music without an explicit creator choice or that the recipe does not allow → no music;
  levels and ducking outside the recipe → the recipe's; transition sounds only at cutaway
  starts, from an available transition effect, when the recipe allows them.

Only a **systemic** failure — the proposal cannot form any valid configuration — raises
``PlanRejected`` (the pipeline then asks the deterministic planner instead).

Explanations are product copy: a planner's sentence is kept only for a section accepted
unchanged and only when it is clean text naming no handles; otherwise the server writes it.
"""

import math
import re
import unicodedata
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from app.services.audio_mix.config import AudioMix, DuckingStrength
from app.services.auto_edit.contract import (
    EXPLANATION_MAX_CHARS,
    MUSIC_HANDLE,
    AutoEditContext,
    AutoEditProposal,
    BrollOption,
)
from app.services.auto_edit.fallback import geometry_layout
from app.services.auto_edit.recipes import MUSIC_LEVEL_DB, MusicLevel, Recipe
from app.services.broll.grounding import invented_names, stem, stems
from app.services.clip_edit.config import CaptionTiming, EditConfig
from app.services.clip_edit.hook import (
    MAX_HOOK_CHARS,
    MIN_HOOK_SECONDS,
    HookConfig,
    normalize_hook_text,
)
from app.services.visuals.assets import VisualsProblem, check_visuals
from app.services.visuals.config import VisualMode, VisualsConfig

EXPLANATIONS_VERSION = "auto_edit_explanations_v1"
SFX_GAIN_DB = -10.0  # transition sounds stay well under the voice
HOOK_GROUNDING_SHARE = 0.6  # at least this share of a hook's content words must be in the clip
_HANDLE = re.compile(r"\b(?:suggestion|visual_asset|music|sfx)_\d+\b")
_TOKEN = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_STOP = frozenset(
    "the and for you your this that with was are but not all can how why what its our out "
    "his her she him they them their there here have has had who will just from into than "
    "then when one".split()
)
LAYOUT_LABELS = {
    "smart_reframe": "Smart Reframe",
    "blur_background": "Blur background",
    "center_crop": "Center crop",
    "fit": "Fit",
}


class PlanRejected(Exception):
    """The proposal cannot form any valid edit configuration (systemic, not optional)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "plan_invalid"
        self.message = message


@dataclass
class ValidationReport:
    """Counters for quality checks (never shown as scores)."""

    unknown_handles: int = 0  # handles the server never issued (invented by the planner)
    unmatched_assets: int = 0  # real assets attached to a suggestion they do not match
    degraded: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedPlan:
    configuration: EditConfig
    explanations: dict[str, Any]
    used_suggestion_ids: tuple[str, ...]
    report: ValidationReport


def clean_text(value: str, limit: int) -> str:
    """NFC, no control/format/private characters, collapsed whitespace."""
    text = unicodedata.normalize("NFC", str(value))
    text = "".join(
        ch if unicodedata.category(ch)[0] != "C" and unicodedata.category(ch) not in ("Zl", "Zp")
        else " "
        for ch in text
    )  # fmt: skip
    return " ".join(text.split())[:limit]


def _explanation(proposed: str, unchanged: bool, server: str) -> str:
    """A planner's sentence only when its section was accepted unchanged and it is clean."""
    if unchanged:
        text = clean_text(proposed, EXPLANATION_MAX_CHARS)
        readable = text[:1].isupper() and "_" not in text  # a sentence, not an identifier
        if 8 <= len(text) and readable and not _HANDLE.search(text) and "://" not in text:
            return text
    return server


def hook_grounded(text: str, sources: str) -> bool:
    """The hook says what the clip says: most content words, every name and every number."""
    source_stems = stems(sources)
    content = [t for t in _TOKEN.findall(text) if len(t) > 2 and t.lower() not in _STOP]
    if not content:
        return False
    found = sum(1 for token in content if stem(token) in source_stems)
    if found < HOOK_GROUNDING_SHARE * len(content):
        return False
    if invented_names(text, source_stems):
        return False
    said_numbers = set(_NUMBER.findall(sources))
    return all(number in said_numbers for number in _NUMBER.findall(text))


def _same_words(a: str, b: str) -> bool:
    def words(text: str) -> list[str]:
        return [stem(token) for token in _TOKEN.findall(text)]

    return bool(words(a)) and words(a) == words(b)


# --- sections -----------------------------------------------------------------------------------


def _layout(proposal, context, recipe, notes) -> tuple[dict[str, Any], dict[str, str]]:
    mode = proposal.layout.mode
    caps = context.capabilities
    usable = (
        caps.smart_reframe
        and context.reframe_analysis_id is not None
        and caps.reframe_confidence in {c.value for c in recipe.smart_reframe_confidence}
    )
    if mode == "smart_reframe" and not usable:
        mode = geometry_layout(context.source_orientation)
        notes.append(
            f"Smart Reframe was not used because framing is not analyzed or not confident "
            f"enough; {LAYOUT_LABELS[mode].lower()} was used instead."
        )
        reason = (
            "Keeps the whole landscape frame so no one is cut off."
            if mode == "blur_background"
            else "The source is already close to vertical."
        )
        return {"layout": mode}, {"choice": LAYOUT_LABELS[mode], "reason": reason}
    fields: dict[str, Any] = {"layout": mode}
    if mode == "smart_reframe":
        fields["reframe_analysis_id"] = context.reframe_analysis_id
        server = "Smart Reframe follows the speaker; framing confidence is good."
    elif mode == "blur_background":
        server = "Keeps the whole frame over a blurred fill."
    elif mode == "center_crop":
        server = "Fills the vertical frame from the centre."
    else:
        server = "Shows the whole frame on a dark background."
    reason = _explanation(proposal.explanations.layout, True, server)
    return fields, {"choice": LAYOUT_LABELS[mode], "reason": reason}


def _captions(proposal, context, recipe, notes) -> tuple[dict[str, Any], dict[str, str]]:
    caps = context.capabilities
    choice = proposal.captions
    if not choice.enabled:
        return {"captions_enabled": False}, {
            "choice": "No captions",
            "reason": _explanation(proposal.explanations.captions, True, "Captions are off."),
        }
    timing_available = caps.word_timing and context.caption_track_id or caps.phrase_timing
    if not caps.text_overlays or not timing_available:
        notes.append("Captions were left out because this clip has no transcript timing yet.")
        return {"captions_enabled": False}, {
            "choice": "No captions",
            "reason": "This clip has no transcript timing yet.",
        }
    unchanged = True
    presets = [p.value for p in recipe.caption_presets]
    positions = [p.value for p in recipe.caption_positions]
    preset, position = choice.preset, choice.position
    if preset not in presets:
        preset, unchanged = presets[0], False
        notes.append(f"The caption style was changed to {preset.title()} to match the recipe.")
    if position not in positions:
        position, unchanged = positions[0], False
    if caps.word_timing and context.caption_track_id:
        timing = CaptionTiming.ALIGNED_WORD.value
        timing_label = "word synced"
        fields = {"caption_track_id": context.caption_track_id}
    else:
        timing = CaptionTiming.PHRASE_FALLBACK.value
        timing_label = "phrase timed"
        fields = {}
    server = (
        "Each spoken word is highlighted as it is said."
        if timing == CaptionTiming.ALIGNED_WORD.value
        else "Captions follow the transcript phrases (word timing is not generated yet)."
    )
    return (
        {
            "captions_enabled": True,
            "caption_style": preset,
            "caption_position": position,
            "caption_timing": timing,
            **fields,
        },
        {
            "choice": f"{preset.title()} captions · {position} · {timing_label}",
            "reason": _explanation(proposal.explanations.captions, unchanged, server),
        },
    )


def _hook(proposal, context, recipe, caption_position, notes) -> tuple[dict, dict[str, str]]:
    choice = proposal.hook
    none = {"choice": "No hook"}
    if not choice.enabled:
        reason = _explanation(proposal.explanations.hook, True, "No opening hook.")
        return {}, {**none, "reason": reason}
    if not recipe.hook_allowed or not context.capabilities.text_overlays:
        notes.append("The hook was left out because this recipe or server does not show one.")
        return {}, {**none, "reason": "No opening hook."}
    sources = " ".join(filter(None, (context.transcript, context.candidate_hook, context.title)))
    candidate = normalize_hook_text(clean_text(context.candidate_hook or "", 200))
    styles = [s.value for s in recipe.hook_styles]
    style = choice.style if choice.style in styles else styles[0]
    seconds = choice.duration_seconds
    if not (math.isfinite(seconds) and MIN_HOOK_SECONDS <= seconds <= recipe.hook_max_seconds):
        seconds = recipe.hook_seconds
    position = "center" if caption_position == "top" else "top"

    def attempt(text: str) -> HookConfig | None:
        try:
            return HookConfig.create(text=text, style=style, position=position, duration=seconds)
        except ValueError:
            return None

    text = normalize_hook_text(clean_text(choice.text, 200))
    reason = "The planner's hook"
    explanation = ""
    problem = None
    if not text:
        problem = "was empty"
    elif len(text) > MAX_HOOK_CHARS:
        problem = "was too long"
    elif text != candidate and not hook_grounded(text, sources):
        # The candidate's own hook comes from the clip's (validated) moment selection.
        problem = "was not grounded in what was said"
    elif context.lines and _same_words(text, context.lines[0].text):
        problem = "repeated the first caption word for word"
    hook = None if problem else attempt(text)
    if hook is None and not problem:
        problem = "did not fit on screen"
    unchanged = problem is None and style == choice.style and seconds == choice.duration_seconds
    if hook is None and candidate and candidate != text:
        hook = attempt(candidate)
        if hook is not None:
            notes.append(f"{reason} {problem}, so the clip's own hook was used instead.")
            explanation = "Uses the clip's own hook from the moment selection."
    if hook is None:
        notes.append(f"{reason} {problem}, so no hook was added.")
        return {}, {**none, "reason": "No hook fits this clip without inventing anything."}
    if problem is None:
        explanation = _explanation(
            proposal.explanations.hook, unchanged, "A short opening line from the clip itself."
        )
    fields = {
        "hook_enabled": True,
        "hook_text": hook.text,
        "hook_style": hook.style.value,
        "hook_position": hook.position.value,
        "hook_duration": hook.duration,
    }
    return fields, {
        "choice": f"“{hook.text}” · {hook.duration:g} s · {hook.position.value}",
        "reason": explanation,
    }


def _element(option: BrollOption, asset_id: str, mode: str, recipe: Recipe) -> dict[str, Any]:
    element: dict[str, Any] = {
        "asset_id": asset_id,
        "mode": mode,
        "start_seconds": option.start,
        "end_seconds": option.end,
        "transition": recipe.transition.value,
    }
    if recipe.transition.value == "fade":
        element["transition_seconds"] = min(
            recipe.transition_seconds, (option.end - option.start) / 2
        )
    if mode == VisualMode.CUTAWAY:
        element["fit"] = recipe.cutaway_fit.value
    else:
        element["position"] = recipe.pip_position.value
    return element


def _visuals(proposal, context, recipe, report, notes):
    choices = proposal.visuals
    options = {option.handle: option for option in context.broll}
    assets = {asset.handle: asset for asset in context.visual_assets}
    server_none = (
        "No project asset matched a B-roll suggestion."
        if context.broll
        else "There were no B-roll suggestions for this clip."
    )
    if not choices:
        reason = _explanation(proposal.explanations.visuals, True, server_none)
        return [], [], {"choice": "No visuals", "reason": reason}
    if not context.capabilities.visuals or not recipe.max_visuals:
        notes.append("Visuals were left out because this recipe or server does not add them.")
        return [], [], {"choice": "No visuals", "reason": server_none}
    modes = [m.value for m in recipe.visual_modes]
    kept: list[dict[str, Any]] = []
    kept_options: list[BrollOption] = []
    items: list[dict[str, Any]] = []
    dropped = paced = 0
    for choice in choices:
        option = options.get(choice.suggestion)
        if option is None or choice.suggestion not in context.suggestion_ids:
            report.unknown_handles += 1
            dropped += 1
            notes.append("A visual pointing at an unknown B-roll suggestion was ignored.")
            continue
        if choice.asset not in context.visual_ids:
            report.unknown_handles += 1
        elif choice.asset not in option.matches:
            report.unmatched_assets += 1
        if choice.asset not in option.matches or choice.asset not in context.visual_ids:
            notes.append(
                f"A visual for “{option.query}” was left out: no project asset matched it."
            )
            dropped += 1
            continue
        if any(o.handle == option.handle for o in kept_options):
            dropped += 1
            continue
        if any(option.start < o.end and option.end > o.start for o in kept_options):
            notes.append(f"A visual for “{option.query}” was left out: it would overlap another.")
            dropped += 1
            continue
        too_close = any(
            option.start < o.end + recipe.min_gap_seconds
            and option.end > o.start - recipe.min_gap_seconds
            for o in kept_options
        )
        if (
            len(kept) >= recipe.max_visuals
            or option.end - option.start < recipe.min_visual_seconds
            or too_close
        ):
            dropped += 1
            paced += 1
            continue
        mode = choice.mode if choice.mode in modes else modes[0]
        asset = assets[choice.asset]
        element = _element(option, context.visual_ids[choice.asset], mode, recipe)
        try:
            single = VisualsConfig.create({"elements": [element]})
            stand_in = SimpleNamespace(kind=asset.kind, duration_seconds=asset.duration)
            check_visuals(single, {element["asset_id"]: stand_in}, context.clip_duration)
        except (ValueError, VisualsProblem):
            notes.append(f"A visual for “{option.query}” was left out: the asset cannot fill it.")
            dropped += 1
            continue
        try:
            VisualsConfig.create({"elements": [*kept, element]})
        except ValueError:
            notes.append(
                f"A visual for “{option.query}” was left out: it would clash with another."
            )
            dropped += 1
            continue
        kept.append(element)
        kept_options.append(option)
        items.append({"start": option.start, "end": option.end, "mode": mode,
                      "asset_name": asset.name, "query": option.query})  # fmt: skip
    if paced:
        notes.append(
            f"{paced} suggested visual{'s were' if paced > 1 else ' was'} left out to keep "
            "this recipe's pacing."
        )
    if not kept:
        return [], [], {"choice": "No visuals", "reason": server_none}
    unchanged = dropped == 0 and all(c.mode in modes for c in choices)
    count = len(kept)
    kinds = {item["mode"] for item in items}
    label = (
        f"{count} cutaway{'s' if count > 1 else ''}" if kinds == {"cutaway"} else f"{count} visuals"
    )
    server = "Supports " + "; ".join(f"“{o.query}”" for o in kept_options) + "."
    reason = _explanation(proposal.explanations.visuals, unchanged, server)
    used = [context.suggestion_ids[o.handle] for o in kept_options]
    return kept, used, {"choice": label, "reason": reason, "items": items}


def _audio(proposal, context, recipe, cutaways, notes) -> tuple[dict | None, dict[str, str]]:
    choice = proposal.audio
    mix: dict[str, Any] = {"source_gain_db": 0.0, "normalize": True, "sfx": []}
    unchanged = True
    parts = ["Original audio, normalized"]
    if choice.use_music:
        music_id = context.audio_ids.get(MUSIC_HANDLE) if context.music else None
        if music_id is None or not recipe.music_allowed:
            notes.append(
                "Music was left out because no track was chosen for this plan."
                if music_id is None
                else "Music was left out because this recipe keeps the original audio only."
            )
            unchanged = False
        else:
            levels = [level.value for level in recipe.music_levels]
            duckings = [d.value for d in recipe.ducking]
            level = choice.music_level if choice.music_level in levels else levels[0]
            ducking = choice.ducking if choice.ducking in duckings else duckings[0]
            unchanged = unchanged and level == choice.music_level and ducking == choice.ducking
            gain = MUSIC_LEVEL_DB[MusicLevel(level)]
            mix["music"] = {
                "asset_id": music_id,
                "gain_db": gain,
                "loop": context.music.duration < context.clip_duration,
                "ducking": DuckingStrength(ducking).value,
            }
            parts.append(f"music {gain:g} dB with {ducking} ducking")
    if choice.transition_sounds:
        sounds = [
            s for s in context.sound_effects if s.transition and s.handle in context.audio_ids
        ]
        if recipe.max_sfx and sounds and cutaways:
            for element in cutaways[: recipe.max_sfx]:
                mix["sfx"].append({
                    "asset_id": context.audio_ids[sounds[0].handle],
                    "at_seconds": max(0.0, element["start_seconds"] - 0.05),
                    "gain_db": SFX_GAIN_DB,
                })  # fmt: skip
            parts.append(f"{len(mix['sfx'])} transition sound{'s' if len(mix['sfx']) > 1 else ''}")
        else:
            unchanged = False
            if recipe.max_sfx and not sounds:
                notes.append("No transition sound was added: no matching sound effect exists.")
    server = (
        "Your music stays under the voice and dips while you speak."
        if "music" in mix
        else "The voice comes first: the original audio, evenly loud."
    )
    reason = _explanation(proposal.explanations.audio, unchanged, server)
    return mix, {"choice": ", ".join(parts).capitalize(), "reason": reason}


# --- the plan -----------------------------------------------------------------------------------


def validate_plan(
    proposal: AutoEditProposal, context: AutoEditContext, recipe: Recipe
) -> ValidatedPlan:
    notes: list[str] = []
    report = ValidationReport()
    layout_fields, layout_x = _layout(proposal, context, recipe, notes)
    caption_fields, captions_x = _captions(proposal, context, recipe, notes)
    hook_fields, hook_x = _hook(
        proposal, context, recipe, caption_fields.get("caption_position"), notes
    )
    elements, used, visuals_x = _visuals(proposal, context, recipe, report, notes)
    cutaways = [e for e in elements if e["mode"] == VisualMode.CUTAWAY]
    audio, audio_x = _audio(proposal, context, recipe, cutaways, notes)
    try:
        configuration = EditConfig.create(
            layout=layout_fields["layout"],
            reframe_analysis_id=layout_fields.get("reframe_analysis_id"),
            captions_enabled=caption_fields["captions_enabled"],
            caption_style=caption_fields.get("caption_style"),
            caption_position=caption_fields.get("caption_position"),
            caption_timing=caption_fields.get("caption_timing"),
            caption_track_id=caption_fields.get("caption_track_id"),
            hook_enabled=bool(hook_fields),
            hook_text=hook_fields.get("hook_text"),
            hook_style=hook_fields.get("hook_style"),
            hook_position=hook_fields.get("hook_position"),
            hook_duration=hook_fields.get("hook_duration"),
            audio=AudioMix.create(audio),
            visuals={"elements": elements} if elements else None,
        )
    except ValueError as error:
        raise PlanRejected("The plan does not form a valid edit configuration") from error
    report.degraded = list(notes)
    explanations = {
        "version": EXPLANATIONS_VERSION,
        "sections": {
            "layout": layout_x,
            "captions": captions_x,
            "hook": hook_x,
            "visuals": visuals_x,
            "audio": audio_x,
        },
        "notes": notes,
    }
    return ValidatedPlan(configuration, explanations, tuple(used), report)
