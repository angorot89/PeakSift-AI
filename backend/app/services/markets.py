"""Markets: where a creator's Shorts are made for, kept separate from the language they speak.

A **market** extends Global PeakSift with local preferences (Morocco Mode is market ``ma``); it
never replaces Global — every Global tool, template and asset stays available in every market.
A **content language** is what a project's videos are in (Darija, Arabic, French, English, mixed
or "auto"): a Moroccan project may well be in French or English, so the two never imply each
other.

Markets are data here, not code paths: business logic asks a ``MarketProfile`` what it prefers
(``local_label``, ``hook_languages``…) instead of testing for Morocco, so a future market is a new
entry, not a rewrite. ``snapshot`` freezes what a Short or a plan was made with (provenance), so
later changes to a profile never rewrite history.
"""

from dataclasses import dataclass
from typing import Any

MARKET_PROFILE_VERSION = "market_v1"
GLOBAL = "global"
CONTENT_LANGUAGES: dict[str, str] = {
    "auto": "Detect from the video",
    "darija": "Darija (Moroccan Arabic)",
    "arabic": "Arabic",
    "french": "French",
    "english": "English",
    "mixed": "Mixed languages",
}


@dataclass(frozen=True)
class MarketProfile:
    code: str
    name: str
    # How local resources are called in this market ("Moroccan visuals"); None for Global.
    local_label: str | None
    # Languages PeakSift can suggest opening hooks in for this market, in preference order.
    # Suggestions in another language are offered only when the creator asks.
    hook_languages: tuple[str, ...]
    # Asset location labels the creator may choose from (never guessed from pixels).
    locations: tuple[str, ...] = ()

    @property
    def is_local(self) -> bool:
        return self.code != GLOBAL

    def read(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "local_label": self.local_label,
            "hook_languages": list(self.hook_languages),
            "locations": list(self.locations),
        }


MARKETS: dict[str, MarketProfile] = {
    GLOBAL: MarketProfile(GLOBAL, "Global", None, ("english", "french", "arabic")),
    "ma": MarketProfile(
        "ma",
        "Morocco",
        "Moroccan",
        ("darija", "french", "arabic", "english"),
        locations=(
            "Casablanca",
            "Marrakech",
            "Rabat",
            "Tangier",
            "Agadir",
            "Fez",
            "Chefchaouen",
            "Atlas",
            "Sahara",
        ),  # fmt: skip
    ),
}


def market(code: str | None) -> MarketProfile:
    """The profile for ``code``; ValueError for anything that is not a known market."""
    profile = MARKETS.get(code or GLOBAL)
    if profile is None:
        raise ValueError("Unknown market")
    return profile


def content_language(value: str | None) -> str:
    if (value or "auto") not in CONTENT_LANGUAGES:
        raise ValueError("Unknown content language")
    return value or "auto"


def snapshot(market_code: str, language: str) -> dict[str, Any] | None:
    """What a Short or plan is frozen with — only when it was made in a local market (Global
    Shorts keep exactly the provenance they had before markets existed)."""
    profile = market(market_code)
    if not profile.is_local:
        return None
    return {"code": profile.code, "name": profile.name, "content_language": language,
            "version": MARKET_PROFILE_VERSION}  # fmt: skip
