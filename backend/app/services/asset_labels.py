"""Where a creator's visuals and sounds come from and what they are (V1.8).

Every asset records its **origin** — how the creator has the right to use it — chosen by the
creator: made by them, owned by their company, licensed (with the licence or source written
down), public domain, or CC0. There is deliberately no "from the internet" origin: PeakSift never
fetches media, and a licensed asset without its licence written down is refused.

A creator may also mark an asset as **local** to a market (Morocco, "ma"), give it a **category**
(organizational only — never a sign of popularity) and, for a local asset, a **location** from the
market's list. Locations come only from the creator; PeakSift never guesses a place from what an
image shows. These labels help local-first ordering in search and Auto Edit; they never hide an
asset, and Global assets stay available everywhere.
"""

from typing import Any

from app.services import markets

ORIGINS: dict[str, str] = {
    "creator_upload": "Made by you",
    "company_owned": "Owned by your company",
    "licensed": "Licensed",
    "public_domain": "Public domain",
    "cc0": "CC0 (no rights reserved)",
}
VISUAL_CATEGORIES: dict[str, str] = {
    "city": "City", "street": "Street", "cafe": "Café", "food": "Food", "travel": "Travel",
    "coast": "Coast", "mountains": "Mountains", "architecture": "Architecture",
    "beauty": "Beauty", "fashion": "Fashion", "business": "Business", "campus": "Campus",
    "sports_atmosphere": "Sports atmosphere", "family_lifestyle": "Family & lifestyle",
}  # fmt: skip
AUDIO_CATEGORIES: dict[str, str] = {
    "cafe_ambience": "Café ambience", "street_ambience": "Street ambience",
    "market_ambience": "Market ambience", "crowd_ambience": "Crowd ambience",
    "celebration_ambience": "Celebration ambience", "transition_sfx": "Transition effect",
    "percussion_sfx": "Percussion effect", "voice_reaction": "Voice reaction",
}  # fmt: skip
LICENSE_NOTE_MAX = 300
FIELDS = ("origin", "license_note", "market", "category", "location")


def categories(family: str) -> dict[str, str]:
    return VISUAL_CATEGORIES if family == "visual" else AUDIO_CATEGORIES


def clean_labels(family: str, current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """The asset's labels after ``changes`` (only the keys sent change), validated together.
    ValueError with a creator-facing message otherwise."""
    labels = {**current, **{k: v for k, v in changes.items() if k in FIELDS}}
    origin = labels.get("origin") or "creator_upload"
    if origin not in ORIGINS:
        raise ValueError("Choose where this asset comes from")
    note = " ".join(str(labels.get("license_note") or "").split()) or None
    if note and len(note) > LICENSE_NOTE_MAX:
        raise ValueError(f"Keep the licence note under {LICENSE_NOTE_MAX} characters")
    if origin == "licensed" and not note:
        raise ValueError("Write down the licence or where you licensed it from")
    try:
        profile = markets.market(labels.get("market"))
    except ValueError:
        raise ValueError("Unknown market") from None
    category = labels.get("category") or None
    if category is not None and category not in categories(family):
        raise ValueError("Unknown category")
    location = labels.get("location") or None
    if not profile.is_local:
        location = None  # a Global asset has no local location
    elif location is not None and location not in profile.locations:
        raise ValueError("Choose a location from the list")
    return {"origin": origin, "license_note": note, "market": profile.code,
            "category": category, "location": location}  # fmt: skip


def read(asset) -> dict[str, Any]:
    return {field: getattr(asset, field) for field in FIELDS}
