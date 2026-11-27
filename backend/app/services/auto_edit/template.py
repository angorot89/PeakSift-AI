"""Applying a creator's Short template and brand to a validated Auto Edit plan.

**Precedence** (strongest first):

1. hard product constraints — what the clip, the server and the editor allow (a completed
   framing analysis, transcript timing, grounded hook words, the visual and audio checks);
2. the creator's explicit per-Short choices — made afterwards in the editor, on the new version;
3. the selected **template** — every setting it fixes;
4. the template's **brand** — logo, colours and end card;
5. the **recipe** (the template's starting style, or the one chosen);
6. performance hints (opt-in, weak, inside the recipe);
7. the planner's own preferences.

The planner (local model or rules) proposes inside the recipe; ``validate_plan`` turns its
proposal into a valid edit; *then* this module applies the template, so a model can never
undo a template setting — a template's Minimal captions stay Minimal, its logo stays on. What a
template cannot force falls back safely with a creator-facing note: Smart Reframe without a
confident analysis keeps Auto Edit's framing, an opening hook needs grounded words from the
clip, music is never added by a template (only its level and ducking when the creator chose
music). The template and brand are taken from the plan's own stored snapshot, so editing them
later never changes the plan.
"""

from dataclasses import replace
from typing import Any

from app.services.audio_mix.config import AudioMix, DuckingStrength
from app.services.auto_edit.contract import AutoEditContext
from app.services.auto_edit.recipes import MUSIC_LEVEL_DB, MusicLevel
from app.services.auto_edit.validation import LAYOUT_LABELS, ValidatedPlan
from app.services.branding.template_config import BrollAmount, Framing, TemplateConfig
from app.services.clip_edit.config import CaptionTiming, EditConfig
from app.services.visuals.config import VisualsConfig

USABLE_REFRAME = {"high", "mixed"}


def _fields(config: EditConfig) -> dict[str, Any]:
    """``EditConfig.create`` keyword arguments that rebuild ``config``."""
    hook = config.hook
    return {
        "layout": config.layout.value,
        "reframe_analysis_id": config.reframe_analysis_id,
        "captions_enabled": config.captions_enabled,
        "caption_style": config.caption_style.value if config.caption_style else None,
        "caption_position": config.caption_position.value if config.caption_position else None,
        "caption_timing": config.caption_timing.value if config.caption_timing else None,
        "caption_track_id": config.caption_track_id,
        "hook_enabled": hook is not None,
        "hook_text": hook.text if hook else None,
        "hook_style": hook.style.value if hook else None,
        "hook_position": hook.position.value if hook else None,
        "hook_duration": hook.duration if hook else None,
        "audio": config.audio,
        "visuals": config.visuals,
        "brand": config.brand,
        "cuts": config.cuts,
    }


def _framing(fields, template: TemplateConfig, context: AutoEditContext, notes) -> None:
    if template.framing == Framing.AUTO:
        return
    if template.framing == Framing.SMART_REFRAME:
        caps = context.capabilities
        if (
            caps.smart_reframe
            and context.reframe_analysis_id
            and caps.reframe_confidence in USABLE_REFRAME
        ):
            fields["layout"] = "smart_reframe"
            fields["reframe_analysis_id"] = context.reframe_analysis_id
        else:
            notes.append(
                "Your template prefers Smart Reframe, but this clip's framing isn't analyzed "
                f"confidently yet, so {LAYOUT_LABELS[fields['layout']].lower()} was kept."
            )
        return
    fields["layout"] = template.framing.value
    fields["reframe_analysis_id"] = None


def _captions(fields, template: TemplateConfig, context: AutoEditContext, notes) -> None:
    if not template.captions:
        fields.update(captions_enabled=False, caption_style=None, caption_position=None)
        fields.update(caption_timing=None, caption_track_id=None)
        return
    if not fields["captions_enabled"]:
        caps = context.capabilities
        if not caps.text_overlays or not (caps.word_timing or caps.phrase_timing):
            notes.append(
                "Your template shows captions, but this clip has no transcript timing yet."
            )
            return
        aligned = caps.word_timing and context.caption_track_id
        fields.update(
            captions_enabled=True,
            caption_timing=(
                CaptionTiming.ALIGNED_WORD if aligned else CaptionTiming.PHRASE_FALLBACK
            ).value,
            caption_track_id=context.caption_track_id if aligned else None,
        )
        fields["caption_style"] = fields["caption_style"] or "focus"
        fields["caption_position"] = fields["caption_position"] or "bottom"
    if template.caption_preset is not None:
        fields["caption_style"] = template.caption_preset.value
        if fields["caption_timing"] is None:  # a phrase style became a dynamic one
            fields["caption_timing"] = CaptionTiming.PHRASE_FALLBACK.value
    if template.caption_position is not None:
        fields["caption_position"] = template.caption_position.value


def _hook(fields, template: TemplateConfig, notes) -> None:
    if not template.hook:
        fields.update(hook_enabled=False, hook_text=None, hook_style=None)
        fields.update(hook_position=None, hook_duration=None)
        return
    if not fields["hook_enabled"]:
        notes.append(
            "Your template shows an opening hook, but no line from this clip worked as one, "
            "so there is none — add one in the editor if you like."
        )
        return
    if template.hook_style is not None:
        fields["hook_style"] = template.hook_style.value
    if template.hook_seconds is not None:
        fields["hook_duration"] = template.hook_seconds
    if template.hook_position is not None:
        fields["hook_position"] = template.hook_position.value
    if fields["captions_enabled"] and fields["hook_position"] == fields["caption_position"]:
        # Never on top of each other: the hook takes the other place.
        fields["hook_position"] = "center" if fields["hook_position"] == "top" else "top"


def _visuals(fields, template: TemplateConfig, notes) -> None:
    visuals: VisualsConfig | None = fields["visuals"]
    elements = visuals.elements if visuals else ()
    if template.broll == BrollAmount.NONE and elements:
        fields["visuals"] = None
        notes.append("Your template uses no B-roll, so the suggested visuals were left out.")
    elif template.broll == BrollAmount.LIGHT and len(elements) > 1:
        fields["visuals"] = VisualsConfig(elements[:1])
        notes.append("Your template keeps B-roll light, so only the first visual was kept.")


def _audio(fields, template: TemplateConfig) -> None:
    mix: AudioMix | None = fields["audio"]
    if mix is None:
        mix = AudioMix()
    music = mix.music
    if music is not None:
        if template.music_level is not None:
            music = replace(music, gain_db=MUSIC_LEVEL_DB[MusicLevel(template.music_level)])
        if template.ducking is not None:
            music = replace(music, ducking=DuckingStrength(template.ducking))
    sfx = mix.sfx if template.sound_effects else ()
    fields["audio"] = AudioMix.from_snapshot(
        replace(mix, music=music, sfx=sfx, normalize=template.normalize_loudness).snapshot()
    )


SECTION_FIELDS = {
    "layout": ("layout",),
    "captions": ("captions_enabled", "caption_style", "caption_position", "caption_timing"),
    "hook": ("hook_enabled", "hook_text", "hook_style", "hook_position", "hook_duration"),
    "visuals": ("visuals",),
    "audio": ("audio",),
}


def _same(before: dict[str, Any], after: dict[str, Any], key: str) -> bool:
    a, b = before[key], after[key]
    if key == "audio":
        a, b = (x.snapshot() if x is not None else None for x in (a, b))
    return a == b


def _audio_choice(mix: AudioMix | None) -> str:
    parts = ["Original audio" + (", normalized" if mix is None or mix.normalize else "")]
    if mix is not None and mix.music is not None:
        parts.append(f"music {mix.music.gain_db:g} dB with {mix.music.ducking.value} ducking")
    if mix is not None and mix.sfx:
        parts.append(f"{len(mix.sfx)} transition sound{'s' if len(mix.sfx) > 1 else ''}")
    return ", ".join(parts)


def _describe(sections: dict, before: dict, after: dict, name: str) -> dict:
    """The plan's sections as rendered: a section the template changed is described from the
    final settings and credited to the template — never the planner's words about a setting it
    no longer has (e.g. "headline style" for a template's boxed hook)."""
    reason = f"Set by your {name} template."
    for section, keys in SECTION_FIELDS.items():
        if all(_same(before, after, key) for key in keys):
            continue
        old = sections.get(section) or {}
        if section == "layout":
            sections[section] = {"choice": LAYOUT_LABELS[after["layout"]], "reason": reason}
        elif section == "captions":
            if not after["captions_enabled"]:
                sections[section] = {"choice": "No captions", "reason": reason}
            else:
                timing = (
                    "word synced"
                    if after["caption_timing"] == CaptionTiming.ALIGNED_WORD.value
                    else "phrase timed"
                )
                sections[section] = {
                    "choice": f"{after['caption_style'].title()} captions · "
                    f"{after['caption_position']} · {timing}",
                    "reason": reason,
                }
        elif section == "hook":
            if not after["hook_enabled"]:
                sections[section] = {"choice": "No hook", "reason": reason}
            else:
                sections[section] = {
                    "choice": f"“{after['hook_text']}” · {after['hook_duration']:g} s · "
                    f"{after['hook_position']}",
                    # The words are still the clip's own; only how they look changed.
                    "reason": f"The clip's own words, styled by your {name} template.",
                }
        elif section == "visuals":
            visuals: VisualsConfig | None = after["visuals"]
            count = len(visuals.elements) if visuals else 0
            if not count:
                sections[section] = {"choice": "No visuals", "reason": reason}
            else:
                items = (old.get("items") or [])[:count]
                sections[section] = {
                    "choice": f"{count} visual{'s' if count > 1 else ''}",
                    "reason": reason,
                    **({"items": items} if items else {}),
                }
        else:
            sections[section] = {"choice": _audio_choice(after["audio"]), "reason": reason}
    return sections


def apply_template(
    validated: ValidatedPlan, template: dict[str, Any], context: AutoEditContext
) -> ValidatedPlan:
    """``validated`` with the template (and its brand) applied — see the module's precedence.
    A combination that cannot form a valid edit keeps the validated plan, with a note."""
    settings = TemplateConfig.from_snapshot(template["config"])
    fields = _fields(validated.configuration)
    notes: list[str] = []
    _framing(fields, settings, context, notes)
    _captions(fields, settings, context, notes)
    _hook(fields, settings, notes)
    _visuals(fields, settings, notes)
    _audio(fields, settings)
    fields["brand"] = template.get("brand")
    explanations = dict(validated.explanations)
    started = f"Started from your {template['name']} template."
    if template.get("brand"):
        started += f" Used your {template['brand']['name']} brand."
    try:
        configuration = EditConfig.create(**fields)
    except ValueError:
        configuration = validated.configuration
        notes = [
            "Some of your template's settings don't fit this clip, so Auto Edit's own choices "
            "were kept."
        ]
    explanations["sections"] = _describe(
        dict(explanations.get("sections") or {}),
        _fields(validated.configuration),
        _fields(configuration),
        template["name"],
    )
    explanations["template"] = {
        "id": template["id"],
        "name": template["name"],
        "version": template["version"],
        "brand": (template.get("brand") or {}).get("name"),
        "summary": started,
    }
    explanations["notes"] = [*explanations.get("notes", []), *notes]
    return ValidatedPlan(
        configuration, explanations, validated.used_suggestion_ids, validated.report
    )
