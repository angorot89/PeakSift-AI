"""Curated template formats for a market (V1.8): Morocco Mode's starting points.

Each format is a **curated** starting point (never "trending": PeakSift has no trend data) made
only of settings the editor and renderer already support — framing, captions, the opening hook,
how much B-roll, music level and ducking, sound effects, logo and end card — on one of the four
recipes. Picking one creates the creator's own template (versioned and frozen into plans like
any other); the format itself carries no media, no slang and no claims. Global starters are
always offered too: a market adds formats, it never hides Global ones.
"""

from dataclasses import dataclass, field
from typing import Any

from app.services.branding.template_config import TemplateConfig


@dataclass(frozen=True)
class MarketStarter:
    key: str
    market: str
    label: str
    description: str
    recipe: str
    settings: dict[str, Any] = field(default_factory=dict)

    def config(self) -> dict[str, Any]:
        return TemplateConfig.create(self.settings).snapshot()


MARKET_STARTERS: tuple[MarketStarter, ...] = (
    MarketStarter(
        "ma_vox_pop", "ma", "Morocco Vox Pop",
        "Street interviews and quick answers: faces kept in frame, big readable captions for "
        "Darija, French or mixed speech, a question as the opening, no B-roll over the people.",
        "punchy",
        {"framing": "smart_reframe", "caption_preset": "punch", "caption_position": "bottom",
         "hook_style": "boxed", "hook_position": "top", "hook_seconds": 2.5, "broll": "none",
         "music_level": "quiet", "ducking": "strong", "sound_effects": False},
    ),
    MarketStarter(
        "ma_darija_reaction", "ma", "Darija Reaction",
        "Reactions and hot takes: the active word emphasised, a short punchy opening and room "
        "for one sound effect.",
        "punchy",
        {"caption_preset": "punch", "caption_position": "center", "hook_style": "headline",
         "hook_position": "top", "hook_seconds": 2.0, "broll": "light", "sound_effects": True,
         "music_level": "low", "ducking": "medium"},
    ),
    MarketStarter(
        "ma_storytime", "ma", "Local Storytime",
        "A story told at its own pace: calm captions, a minimal opening and B-roll from your own "
        "visuals where it helps.",
        "story",
        {"caption_preset": "focus", "caption_position": "bottom", "hook_style": "minimal",
         "hook_position": "top", "broll": "recipe", "music_level": "low", "ducking": "medium"},
    ),
    MarketStarter(
        "ma_explainer", "ma", "Lesson / Explainer",
        "Tips and explanations: boxed captions that stay readable in Arabic script and Latin "
        "letters, a clear opening and at most one visual.",
        "clean",
        {"caption_preset": "boxed", "caption_position": "bottom", "hook_style": "boxed",
         "hook_position": "top", "broll": "light", "sound_effects": False, "music_level": "quiet",
         "ducking": "strong"},
    ),
    MarketStarter(
        "ma_product_showcase", "ma", "Morocco Product Showcase",
        "A product or a shop: the whole frame kept (fit), your logo and an end card, and your own "
        "product visuals.",
        "clean",
        {"framing": "fit", "caption_preset": "minimal", "caption_position": "bottom",
         "hook_style": "headline", "hook_position": "top", "broll": "recipe", "logo": True,
         "end_card": True, "end_card_seconds": 2.0, "music_level": "low", "ducking": "medium"},
    ),
    MarketStarter(
        "ma_food_place", "ma", "Food & Place Review",
        "A café, a dish or a place: the story first, B-roll from your own footage of it, and a "
        "warm music bed under your voice when you pick music.",
        "story",
        {"caption_preset": "focus", "caption_position": "bottom", "hook_style": "headline",
         "hook_position": "top", "broll": "recipe", "music_level": "low", "ducking": "medium"},
    ),
    MarketStarter(
        "ma_talking_head", "ma", "Clean Talking Head",
        "Just you and your words: minimal captions, no opening overlay, no B-roll, no effects.",
        "minimal",
        {"caption_preset": "minimal", "caption_position": "bottom", "hook": False,
         "broll": "none", "sound_effects": False},
    ),
)  # fmt: skip


def market_starters(market: str) -> list[MarketStarter]:
    return [starter for starter in MARKET_STARTERS if starter.market == market]
