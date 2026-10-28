"""What Ask PeakSift knows about the creator's brands and Short templates (V1.7).

**Context** (``branding_view``): the creator's brands (name, default), templates (handle, name,
default, starting style and a few creator words — never ids) and, in the editor, where the
current version came from: its template and brand, the template version it was made with, the
template's version now, and how the version differs from the template now.

**PeakSift's own answers** (``branding_answer``) — exact, from the data, never the model:

- "What template am I using?" — this version's template (editor), else the default one;
- "Do I have a default brand?";
- "Use my Punchy Gaming template" — a *Use this template* button that starts Auto Edit for this
  clip with it (only where there is a clip), else *Open the template*;
- "Why does this Short look different from my template?" — the template changed after the Short
  was made (Shorts keep their settings), and the differences that remain.

"Which template fits this clip?" goes to the model, with a rule: a suggestion, said as one, and
— without enough published history — saying so instead of implying evidence. The Copilot never
changes or deletes a template or brand.
"""

import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BrandProfile, ClipEdit, PublishedContent, ShortTemplate, User
from app.services.branding.template_config import BrollAmount, TemplateConfig

MAX_TEMPLATES = 8

TEMPLATE_IN_USE = re.compile(
    r"\b(what|which)\s+template\b[^?]{0,30}\b(am i|is this|did|does|using|used)\b"
    r"|\btemplate\b[^?]{0,20}\b(am i using|is this short using|this short)\b|\bquel modèle\b",
    re.IGNORECASE,
)
DEFAULT_BRAND = re.compile(
    r"\b(default|my)\s+brand\b|\bdo i have a brand\b|\bma marque\b", re.IGNORECASE
)
USE_TEMPLATE = re.compile(
    r"\buse\s+(?:my\s+|the\s+)?[“\"']?(?P<name>.+?)[”\"']?\s+template\b", re.IGNORECASE
)
WHY_DIFFERENT = re.compile(
    r"\b(look|looks|is)\s+different\b[^?]{0,40}\btemplate\b"
    r"|\bdoes(n'?t| not)\s+match\b[^?]{0,20}\btemplate\b"
    r"|\bdifferent from my template\b",
    re.IGNORECASE,
)

WHICH_FITS = re.compile(
    r"\b(which|what)\s+template\b[^?]{0,40}\b(fit|fits|suit|suits|should i use|best|work)",
    re.IGNORECASE,
)
# A moment's kind → the starting style that usually suits it (a judgement, never a prediction).
STYLE_FOR_KIND = {
    "funny": "punchy", "reaction": "punchy", "hot-take": "punchy", "conflict": "punchy",
    "story": "story", "emotional": "story", "insight": "clean", "explanation": "clean",
}  # fmt: skip
ENOUGH_HISTORY = 10  # published Shorts before history could say anything

LABEL = {"focus": "Focus", "punch": "Punch", "minimal": "Minimal", "boxed": "Boxed",
         "headline": "Headline"}  # fmt: skip


def _label(value: object) -> str:
    return LABEL.get(str(value), str(value).replace("_", " ").title())


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _words(config: TemplateConfig) -> str:
    parts = []
    parts.append(
        f"{LABEL[config.caption_preset.value] if config.caption_preset else 'the style’s'} captions"
        if config.captions
        else "no captions"
    )
    parts.append(
        f"{LABEL[config.hook_style.value]} hook"
        if config.hook and config.hook_style
        else ("no hook" if not config.hook else "a hook")
    )
    parts.append(
        {"none": "no B-roll", "light": "light B-roll", "recipe": "B-roll as the style suggests"}[
            config.broll.value
        ]
    )
    if config.end_card:
        parts.append(f"end card +{config.end_card_seconds:g}s")
    return ", ".join(parts)


def differences(edit_config: dict, template: TemplateConfig) -> list[str]:
    """How a version differs from a template's settings now, in creator words."""
    out: list[str] = []
    captions = edit_config.get("captions") or {}
    if template.captions != bool(captions.get("enabled")):
        out.append("captions are " + ("off" if not captions.get("enabled") else "on") + " here")
    elif template.caption_preset and captions.get("style") != template.caption_preset.value:
        out.append(
            f"captions are {_label(captions.get('style'))} "
            f"here (template: {LABEL[template.caption_preset.value]})"
        )
    hook = edit_config.get("hook")
    if (
        template.hook
        and template.hook_style
        and hook
        and hook.get("style") != template.hook_style.value
    ):
        out.append(
            f"the hook is {_label(hook.get('style'))} here "
            f"(template: {LABEL[template.hook_style.value]})"
        )
    if template.hook and not hook:
        out.append("there is no opening hook here")
    count = len((edit_config.get("visuals") or {}).get("elements") or [])
    if template.broll == BrollAmount.NONE and count:
        out.append(
            f"{count} visual{'s' if count != 1 else ''} were added here (template: no B-roll)"
        )
    brand = edit_config.get("brand") or {}
    if template.end_card and not brand.get("end_card"):
        out.append("there is no end card here")
    if not template.end_card and brand.get("end_card"):
        out.append("this Short has an end card (template: none)")
    return out


def branding_view(db: Session, user: User, handles, target_factory, edit: ClipEdit | None) -> dict:
    """The creator's brands and templates for the Copilot (``handles.add`` gives template
    handles); ``edit`` is the version open in the editor, if any."""
    brands = list(db.scalars(select(BrandProfile).where(BrandProfile.user_id == user.id)))
    templates = list(
        db.scalars(
            select(ShortTemplate)
            .where(ShortTemplate.user_id == user.id)
            .order_by(ShortTemplate.is_default.desc(), ShortTemplate.updated_at.desc())
            .limit(MAX_TEMPLATES)
        )
    )
    listed = []
    for template in templates:
        handle = handles.add(
            "template",
            target_factory("template", template.id, f"Template: {template.name[:48]}", {}),
        )
        listed.append(
            {
                "handle": handle,
                "name": template.name,
                "default": template.is_default,
                "starting_style": template.recipe,
                "brand": template.brand.name if template.brand else None,
                "settings": _words(TemplateConfig.from_snapshot(template.config)),
            }
        )
    published = db.scalar(
        select(func.count())
        .select_from(PublishedContent)
        .where(PublishedContent.user_id == user.id)
    )
    view: dict[str, Any] = {
        "published_shorts": published or 0,
        "brands": [
            {"name": b.name, "default": b.is_default, "has_logo": b.logo_asset_id is not None}
            for b in brands
        ],
        "templates": listed,
    }
    origin = (edit.origin or {}) if edit is not None else {}
    made = origin.get("template")
    if edit is not None:
        current: dict[str, Any] = {
            "template": made["name"] if made else None,
            "brand": (origin.get("brand") or {}).get("name"),
        }
        if made:
            now = db.scalar(
                select(ShortTemplate).where(
                    ShortTemplate.id == uuid.UUID(made["id"]), ShortTemplate.user_id == user.id
                )
            )
            current["made_with_version"] = made["version"]
            current["template_version_now"] = now.version if now else None
            if now is not None:
                current["differences"] = differences(
                    edit.config, TemplateConfig.from_snapshot(now.config)
                )
        view["current_short"] = current
    return view


def branding_answer(view: dict, text: str, *, has_clip: bool) -> tuple[str, str] | None:
    """PeakSift's own answer about brands and templates, as (kind, text), or None."""
    branding = view.get("branding")
    if not isinstance(branding, dict):
        return None
    templates = branding.get("templates") or []
    current = branding.get("current_short")
    default = next((t for t in templates if t["default"]), None)
    if WHY_DIFFERENT.search(text):
        if not current:
            return None
        if not current.get("template"):
            return (
                "brand_studio",
                "This Short didn't start from a template, so there is nothing to compare it with.",
            )
        name = current["template"]
        if current.get("template_version_now") is None:
            return "brand_studio", (
                f"This Short started from “{name}”, which has since been deleted. Shorts keep the "
                "settings they were made with."
            )
        parts = []
        if current["template_version_now"] != current.get("made_with_version"):
            parts.append(
                f"“{name}” changed after this Short was made (version "
                f"{current.get('made_with_version')} → {current['template_version_now']}); Shorts "
                "keep the settings they were made with."
            )
        diffs = current.get("differences") or []
        if diffs:
            parts.append("Compared with the template now: " + "; ".join(diffs) + ".")
        if not parts:
            parts.append(
                f"It matches your “{name}” template. Changes you make in the editor apply to this "
                "Short only."
            )
        return "none", " ".join(parts)
    if TEMPLATE_IN_USE.search(text):
        if current and current.get("template"):
            brand = f" with your “{current['brand']}” brand" if current.get("brand") else ""
            return "none", f"This Short started from your “{current['template']}” template{brand}."
        if default:
            return f"template:{default['handle']}", (
                f"Your default template is “{default['name']}” ({default['settings']}). New Shorts "
                "start from it; you can change anything for each Short."
            )
        return "brand_studio", (
            "You don't have a default template yet. Templates save how your Shorts are edited — "
            "create one in Brand Studio."
        )
    if DEFAULT_BRAND.search(text):
        brand = next((b for b in branding.get("brands") or [] if b["default"]), None)
        if brand:
            logo = " with a logo" if brand["has_logo"] else " (no logo yet)"
            return "brand_studio", f"Yes — your default brand is “{brand['name']}”{logo}."
        return (
            "brand_studio",
            "You don't have a brand yet. Create one in Brand Studio: colours, logo and an end "
            "card.",
        )
    if WHICH_FITS.search(text) and templates:
        clip = (view.get("current") or {}).get("clip") or {}
        return _which_fits(templates, clip, branding.get("published_shorts", 0))
    match = USE_TEMPLATE.search(text)
    if match:
        wanted = _norm(match.group("name"))
        found = next(
            (t for t in templates if _norm(t["name"]) == wanted or wanted in _norm(t["name"])), None
        )
        if found is None:
            return (
                "brand_studio",
                "I can't find a template with that name. Your templates are in Brand Studio.",
            )
        if has_clip:
            return f"use:{found['handle']}", (
                f"Here's Auto Edit with your “{found['name']}” template for this clip — you can "
                "still change anything before rendering."
            )
        return f"template:{found['handle']}", (
            f"Open a clip’s Create a Short to use “{found['name']}”, or set it as your default so "
            "every new Short starts from it."
        )
    return None


def _which_fits(templates: list[dict], clip: dict, published: int) -> tuple[str, str]:
    """A suggestion from what the clip is like and each template's starting style."""
    kind = clip.get("kind")
    style = STYLE_FOR_KIND.get(str(kind))
    matching = [t for t in templates if style and t.get("starting_style") == style]
    default = next((t for t in templates if t["default"]), None)
    chosen = matching[0] if matching else (default or templates[0])
    seconds = clip.get("seconds")
    about = (
        f"this is a {seconds:g}s {kind} moment"
        if kind and isinstance(seconds, int | float)
        else (f"this is a {kind} moment" if kind else "it's your default")
    )
    if matching:
        reason = (
            f"“{chosen['name']}” is a reasonable fit because {about} and it starts from the "
            f"{style.title()} style."
        )
    elif chosen is default:
        reason = (
            f"“{chosen['name']}”, your default, is a reasonable start — none of your templates "
            f"is made for {about.replace('this is ', '')}."
        )
    else:
        reason = f"“{chosen['name']}” is a reasonable start."
    history = (
        " Your performance history isn't large enough to prefer one statistically."
        if published < ENOUGH_HISTORY
        else ""
    )
    return f"use:{chosen['handle']}", f"{reason} This is a suggestion, not a prediction.{history}"
