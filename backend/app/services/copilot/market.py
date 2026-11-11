"""Ask PeakSift in Morocco Mode (V1.8): market facts in the bounded view, and PeakSift's own
answers for what it knows exactly — never the model's.

The view gains a small ``market`` section (the project's market and language, the creator's
local visuals, sounds and templates by name, the curated formats) when the project is in a local
market or the question is about one. These are database facts, so the questions they settle are
answered here, deterministically, in plain words:

- "Do I have any Moroccan visuals / sounds?" — names and counts;
- "Which Morocco template fits this clip?" — a curated format for the moment's kind (an
  editorial pairing, never a prediction), and the creator's own Morocco templates;
- "Can I keep this Short in French?" — yes: the market never changes the language;
- "Give me 3 Darija hooks" — the clip's own Darija lines (quoted from the transcript), or a
  plain no when the clip is not in Darija (PeakSift never writes Darija the creator did not say);
- "What can I use from the Global library?" — the Global visuals, sounds and templates;
- "Use local assets if they fit" — what Morocco Mode already does, and where;
- "Write an opening line" — the clip's own lines, never an opening the model wrote;
- "Is this good for Moroccans?" / "Will Moroccans like this?" — PeakSift never predicts how an
  audience reacts or speaks for a group: it says so, with the project's facts.

No stereotypes, places, slang, prices or audience claims: only names, counts and the creator's
own words. Answers are in English, like PeakSift's other own answers.
"""

import re
from typing import Any

from sqlalchemy import func, select

from app.models import AudioAsset, Project, ShortTemplate, VisualAsset
from app.services import hooks, language, markets
from app.services.asset_labels import AUDIO_CATEGORIES
from app.services.branding.market_starters import MARKET_STARTERS

MARKET_WORDS = re.compile(
    r"morocc|moroccan|maroc|marocain|darija|المغرب|مغربي|الدارجة|local|locaux|locale|global",
    re.IGNORECASE,
)
HAVE_LOCAL = re.compile(
    r"(do i have|have i got|any|est-ce que j'ai|j'ai des|wach 3ndi|واش عندي|عندي).*"
    r"(morocc|moroccan|maroc|marocain|local|مغربي|محلي)",
    re.IGNORECASE,
)
TEMPLATE_FIT = re.compile(
    r"(which|what|quel|quelle|أي).*(morocc|maroc|local|مغربي).*(template|format|modèle|قالب)"
    r"|(morocc|maroc|local).*(template|format|modèle).*(fit|suit|convient|clip)",
    re.IGNORECASE,
)
KEEP_LANGUAGE = re.compile(
    r"(keep|stay|leave|garder|rester|laisser|نخلي|نبقى).*(in |en )?"
    r"(french|english|arabic|darija|français|francais|anglais|arabe|بالفرنسية|بالعربية)",
    re.IGNORECASE,
)
DARIJA_HOOKS = re.compile(
    r"darija.*(hook|opening|accroche)|(hook|opening|accroche)s?.*darija|هوك.*بالدارجة",
    re.IGNORECASE,
)
GLOBAL_LIBRARY = re.compile(
    r"global (library|alternative|asset|visual|sound|template)|from the global|"
    r"bibliothèque (globale|mondiale)|alternative globale",
    re.IGNORECASE,
)
USE_LOCAL = re.compile(r"use (my )?(local|moroccan|morocco) (asset|visual|sound|b-roll)",
                       re.IGNORECASE)  # fmt: skip
AUDIENCE = re.compile(
    r"(good|right|great|work|land|appeal|resonate|popular|like|enjoy|love|watch|connect|plai|aime|"
    r"march|bon)\w*\b.*"
    r"\b(moroccans|moroccan (audience|viewers|people|public)|people in morocco|marocains|"
    r"le public marocain|المغاربة|الجمهور المغربي)"
    r"|\b(will|would|do|are)\s+(moroccans|moroccan (audiences?|viewers|people))\b"
    r"|(يعجب|تعجب|يحبو|مناسب|زوين|مزيان).*(المغاربة|الجمهور المغربي)",
    re.IGNORECASE,
)
OPENING = re.compile(
    r"\b(write|give|suggest|propose|need|want|make|draft|any|écris|donne|propose|trouve|"
    r"اكتب|عطيني|اقترح)\w*\b.*\b(opening|hooks?|accroches?|intro line|first line|"
    r"première phrase|بداية|هوك)\b",
    re.IGNORECASE,
)
MAX_NAMES = 8
FORMAT_FOR_CATEGORY = {
    "story": "Local Storytime", "humor": "Darija Reaction", "reaction": "Darija Reaction",
    "insight": "Lesson / Explainer", "educational": "Lesson / Explainer",
    "emotional": "Local Storytime", "controversial": "Darija Reaction",
}  # fmt: skip


def asks_about_market(text: str) -> bool:
    return bool(MARKET_WORDS.search(text))


def market_view(
    db, user, project: Project | None, question: str, clip=None
) -> dict[str, Any] | None:
    """The market facts for the view: only in a local market's project, or when asked."""
    if project is None or not (markets.market(project.market).is_local
                               or asks_about_market(question)):  # fmt: skip
        return None
    profile = markets.market(project.market if project.market != "global" else "ma")

    def names(model, local: bool) -> tuple[list[str], int]:
        condition = model.market == profile.code if local else model.market == "global"
        rows = db.scalars(
            select(model.display_name).where(model.project_id == project.id, condition)
            .order_by(model.created_at.desc()).limit(MAX_NAMES)
        ).all()  # fmt: skip
        total = db.scalar(
            select(func.count()).select_from(model)
            .where(model.project_id == project.id, condition)
        )  # fmt: skip
        return list(rows), int(total or 0)

    local_visuals, local_visual_total = names(VisualAsset, True)
    global_visuals, global_visual_total = names(VisualAsset, False)
    local_sounds, local_sound_total = names(AudioAsset, True)
    _, global_sound_total = names(AudioAsset, False)
    categories = db.scalars(
        select(AudioAsset.category).where(AudioAsset.project_id == project.id,
                                          AudioAsset.market == profile.code,
                                          AudioAsset.category.is_not(None)).distinct()
    ).all()  # fmt: skip
    templates = db.scalars(
        select(ShortTemplate.name).where(ShortTemplate.user_id == user.id,
                                         ShortTemplate.market == profile.code)
        .order_by(ShortTemplate.name)
    ).all()  # fmt: skip
    return {
        "project_market": markets.market(project.market).name,
        "local_market": profile.name,
        "language": markets.CONTENT_LANGUAGES[project.content_language],
        "local_visuals": local_visuals, "local_visual_total": local_visual_total,
        "global_visuals": global_visuals, "global_visual_total": global_visual_total,
        "local_sounds": local_sounds, "local_sound_total": local_sound_total,
        "global_sound_total": global_sound_total,
        "local_sound_kinds": sorted(AUDIO_CATEGORIES[c] for c in categories if c),
        "local_templates": list(templates),
        "curated_formats": [s.label for s in MARKET_STARTERS if s.market == profile.code],
        "clip_category": clip.candidate.category if clip is not None else None,
    }  # fmt: skip


def _quoted(items: list[str]) -> str:
    shown = [f"“{name}”" for name in items[:3]]
    more = len(items) - 3
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def _clip_lines(view: dict) -> list[str]:
    return [line["text"] for line in view.get("transcript_excerpt") or [] if line.get("text")]


def market_answer(view: dict, text: str):
    """PeakSift's own answer to a market question, as (kind, text), or None."""
    facts = view.get("market")
    if not isinstance(facts, dict):
        return None
    local = facts["local_market"]
    adjective = {"Morocco": "Moroccan"}.get(local, local)
    if AUDIENCE.search(text):
        visuals = facts["local_visual_total"]
        return "none", (
            f"PeakSift can't tell how {adjective} viewers — or any audience — will react, and "
            "it never predicts performance or speaks for a group of people. What it can tell "
            f"you: this project is made for {local}, set to "
            + (facts["language"].lower() if facts["language"] != "Detect from the video"
               else "detect its language")
            + f", with {visuals} {adjective} visual{'s' if visuals != 1 else ''} ready. After "
            "you publish, Analytics shows how your own Shorts are doing."
        )  # fmt: skip
    if KEEP_LANGUAGE.search(text):
        chosen = facts["language"]
        setting = "detect its language" if chosen == markets.CONTENT_LANGUAGES["auto"] else chosen
        return "none", (
            f"Yes. {local} Mode never changes your language: this project is set to {setting}, "
            "captions use your words as you said them, and hook ideas start from your clip's own "
            "lines. Darija, Arabic, French, English or a mix all work."
        )
    if DARIJA_HOOKS.search(text):
        lines = _clip_lines(view)
        ideas = [i for i in hooks.transcript_ideas(" ".join(lines))
                 if i.language in ("darija", "mixed")]  # fmt: skip
        if not ideas:
            return "none", (
                "Your clip isn't in Darija, so PeakSift has no Darija lines to offer: it only "
                "offers Darija from words you said, never written for you. You can write your own "
                "opening in the editor (Arabic script and Latin letters both work)."
            )
        quoted = " ".join(f"“{i.text}”" for i in ideas[:3])
        return "none", (
            f"From your clip's own words: {quoted} In the editor's Opening tool, Hook ideas can "
            "also show them in the other script."
        )
    if OPENING.search(text) and not TEMPLATE_FIT.search(text):
        ideas = hooks.transcript_ideas(" ".join(_clip_lines(view)))
        if not ideas:
            return "none", (
                "Your clip has no sentence that works as an opening yet. PeakSift offers "
                "openings only from your own words — write one in the editor's Opening tool."
            )
        quoted = " ".join(f"“{i.text}”" for i in ideas[:3])
        return "none", (
            f"From your clip's own words: {quoted} PeakSift offers openings only from what you "
            "said; the editor's Opening tool shows them as Hook ideas, in another script or "
            "language where it can do that faithfully."
        )
    if TEMPLATE_FIT.search(text):
        formats = facts["curated_formats"]
        moment_category = facts.get("clip_category")
        suggestion = FORMAT_FOR_CATEGORY.get(moment_category or "")
        mine = facts["local_templates"]
        parts = []
        if suggestion:
            parts.append(
                f"For a {moment_category} moment, the curated “{suggestion}” format is a natural "
                "start (an editorial pairing, not a prediction)."
            )
        parts.append(f"{local} formats: {', '.join(formats)}.")
        if mine:
            parts.append(f"Your own {adjective} templates: {_quoted(mine)}.")
        parts.append("Global templates stay available too.")
        return "brand_studio", " ".join(parts)
    if GLOBAL_LIBRARY.search(text):
        return "assets", (
            f"Everything Global stays available in {local} Mode: "
            f"{facts['global_visual_total']} Global visual"
            f"{'s' if facts['global_visual_total'] != 1 else ''}"
            + (f" ({_quoted(facts['global_visuals'])})" if facts["global_visuals"] else "")
            + f", {facts['global_sound_total']} Global sound"
            f"{'s' if facts['global_sound_total'] != 1 else ''}, and the Clean, Punchy, Story and "
            "Minimal templates. Search ranks your local matches first and keeps Global "
            "alternatives right after them."
        )  # fmt: skip
    if USE_LOCAL.search(text):
        return "assets", (
            f"{local} Mode already does this: search and Auto Edit put your {adjective} visuals "
            "first when they match as strongly as a Global one, and never force one that doesn't "
            f"fit. You have {facts['local_visual_total']} {adjective} visual"
            f"{'s' if facts['local_visual_total'] != 1 else ''} in this project."
        )  # fmt: skip
    if HAVE_LOCAL.search(text):
        visuals, sounds = facts["local_visual_total"], facts["local_sound_total"]
        if not visuals and not sounds:
            return "assets", (
                f"Not yet: no visual or sound in this project is marked {adjective}. In Assets, "
                f"open one you made or licensed and set its market to {adjective}. Your Global "
                "visuals and sounds stay available."
            )
        parts = []
        if visuals:
            parts.append(f"{visuals} {adjective} visual{'s' if visuals != 1 else ''} "
                         f"({_quoted(facts['local_visuals'])})")  # fmt: skip
        if sounds:
            kinds = facts["local_sound_kinds"]
            parts.append(f"{sounds} {adjective} sound{'s' if sounds != 1 else ''}"
                         + (f" ({', '.join(kinds).lower()})" if kinds else ""))  # fmt: skip
        return "assets", f"Yes: {' and '.join(parts)} in this project."
    return None


def detected_language(lines: list[str]) -> str:
    return language.label(language.detect(" ".join(lines)))
