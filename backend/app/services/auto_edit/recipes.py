"""Creator recipes: a small, versioned set of creative intents for Auto Edit.

A recipe is **preferences and bounds**, not a fixed output. It says which framing, caption
presets and positions, hook styles and lengths, how many and which kinds of visuals, and how
loud music may be — always as values the existing editor and renderer already accept. A
planner (the local model or the deterministic fallback) chooses inside these bounds and may
choose less: no hook, no B-roll or no music when the clip or the project's assets make that
the better edit. The server re-checks every choice against the recipe and what exists.

Recipes are versioned (``punchy_v1``). A plan records the exact version it used and is always
re-read with that version, so improving a recipe later never changes an old plan.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.models import AutoEditRecipe, ReframeConfidence
from app.services.audio_mix.config import DuckingStrength
from app.services.clip_edit.config import CaptionPosition, DynamicPreset
from app.services.clip_edit.hook import HookStyle
from app.services.visuals.config import VisualFit, VisualMode, VisualPosition, VisualTransition


class MusicLevel(StrEnum):
    """Creator-level music loudness; the server maps it to dB (never a free number)."""

    QUIET = "quiet"
    LOW = "low"
    MEDIUM = "medium"


MUSIC_LEVEL_DB: dict[MusicLevel, float] = {
    MusicLevel.QUIET: -24.0,
    MusicLevel.LOW: -20.0,
    MusicLevel.MEDIUM: -16.0,
}


@dataclass(frozen=True)
class Recipe:
    name: AutoEditRecipe
    version: str
    label: str
    description: str  # one short creator-facing line
    intent: str  # what the planner should aim for, in editor's terms
    # Framing: Smart Reframe only from a completed analysis at one of these confidence levels;
    # otherwise the source geometry decides (see planner fallback).
    smart_reframe_confidence: tuple[ReframeConfidence, ...]
    # Captions (the dynamic renderer); the first preset is the recipe's default.
    caption_presets: tuple[DynamicPreset, ...]
    caption_positions: tuple[CaptionPosition, ...]
    # Hook: allowed at all, its styles (first = default), and its length on screen.
    hook_allowed: bool
    hook_styles: tuple[HookStyle, ...]
    hook_seconds: float
    hook_max_seconds: float
    # Visuals: how many at most, which modes, how they appear, and pacing.
    max_visuals: int
    visual_modes: tuple[VisualMode, ...]
    cutaway_fit: VisualFit
    pip_position: VisualPosition
    transition: VisualTransition
    transition_seconds: float
    min_visual_seconds: float  # shorter suggested moments are skipped (longer holds)
    min_gap_seconds: float  # breathing room between two visuals
    # Audio: music only from an explicit creator choice, at these levels and ducking.
    music_levels: tuple[MusicLevel, ...]
    ducking: tuple[DuckingStrength, ...]
    max_sfx: int  # transition effects at cutaway starts, only from matching assets

    @property
    def music_allowed(self) -> bool:
        return bool(self.music_levels)

    def summary(self) -> dict[str, Any]:
        """What a planner is told about the recipe (bounds, never internals)."""
        return {
            "recipe": self.name.value,
            "intent": self.intent,
            "caption_presets": [p.value for p in self.caption_presets],
            "caption_positions": [p.value for p in self.caption_positions],
            "hook_allowed": self.hook_allowed,
            "hook_styles": [s.value for s in self.hook_styles],
            "hook_max_seconds": self.hook_max_seconds,
            "max_visuals": self.max_visuals,
            "visual_modes": [m.value for m in self.visual_modes],
            "music_levels": [level.value for level in self.music_levels],
            "ducking": [d.value for d in self.ducking],
            "sound_effects_allowed": self.max_sfx > 0,
        }


_RECIPES: tuple[Recipe, ...] = (
    Recipe(
        name=AutoEditRecipe.CLEAN,
        version="clean_v1",
        label="Clean",
        description="Professional and clear, with little on screen besides you.",
        intent=(
            "Professional and clear. Low visual noise: only visuals that clearly help, a "
            "restrained hook, quiet music if any, no sound effects."
        ),
        smart_reframe_confidence=(ReframeConfidence.HIGH,),
        caption_presets=(DynamicPreset.FOCUS, DynamicPreset.MINIMAL, DynamicPreset.BOXED),
        caption_positions=(CaptionPosition.BOTTOM,),
        hook_allowed=True,
        hook_styles=(HookStyle.MINIMAL, HookStyle.HEADLINE),
        hook_seconds=2.0,
        hook_max_seconds=2.5,
        max_visuals=2,
        visual_modes=(VisualMode.CUTAWAY, VisualMode.PIP),
        cutaway_fit=VisualFit.FILL,
        pip_position=VisualPosition.TOP_RIGHT,
        transition=VisualTransition.FADE,
        transition_seconds=0.3,
        min_visual_seconds=1.5,
        min_gap_seconds=4.0,
        music_levels=(MusicLevel.QUIET, MusicLevel.LOW),
        ducking=(DuckingStrength.MEDIUM, DuckingStrength.STRONG),
        max_sfx=0,
    ),
    Recipe(
        name=AutoEditRecipe.PUNCHY,
        version="punchy_v1",
        label="Punchy",
        description="High-energy short-form: bold captions, a sharp hook, quick cutaways.",
        intent=(
            "High-energy short-form, but never chaotic. Bold word captions, a concise hook, "
            "relevant cutaways with quick cuts, music a little more present, and at most a "
            "couple of transition sounds where a matching effect exists."
        ),
        smart_reframe_confidence=(ReframeConfidence.HIGH, ReframeConfidence.MIXED),
        caption_presets=(DynamicPreset.PUNCH, DynamicPreset.BOXED),
        caption_positions=(CaptionPosition.BOTTOM, CaptionPosition.CENTER),
        hook_allowed=True,
        hook_styles=(HookStyle.HEADLINE, HookStyle.BOXED),
        hook_seconds=2.0,
        hook_max_seconds=2.5,
        max_visuals=4,
        visual_modes=(VisualMode.CUTAWAY, VisualMode.PIP),
        cutaway_fit=VisualFit.FILL,
        pip_position=VisualPosition.TOP_RIGHT,
        transition=VisualTransition.NONE,
        transition_seconds=0.3,
        min_visual_seconds=1.0,
        min_gap_seconds=2.5,
        music_levels=(MusicLevel.LOW, MusicLevel.MEDIUM),
        ducking=(DuckingStrength.MEDIUM, DuckingStrength.STRONG),
        max_sfx=2,
    ),
    Recipe(
        name=AutoEditRecipe.STORY,
        version="story_v1",
        label="Story",
        description="For explainers and stories: calm captions and meaningful cutaways.",
        intent=(
            "Narrative or explainer. Smooth pacing, readable captions, meaningful cutaways held "
            "long enough to register, a restrained hook, quiet music under the voice."
        ),
        smart_reframe_confidence=(ReframeConfidence.HIGH, ReframeConfidence.MIXED),
        caption_presets=(DynamicPreset.FOCUS, DynamicPreset.MINIMAL),
        caption_positions=(CaptionPosition.BOTTOM,),
        hook_allowed=True,
        hook_styles=(HookStyle.MINIMAL, HookStyle.HEADLINE),
        hook_seconds=2.0,
        hook_max_seconds=2.5,
        max_visuals=3,
        visual_modes=(VisualMode.CUTAWAY,),
        cutaway_fit=VisualFit.FILL,
        pip_position=VisualPosition.TOP_RIGHT,
        transition=VisualTransition.FADE,
        transition_seconds=0.4,
        min_visual_seconds=2.0,
        min_gap_seconds=4.0,
        music_levels=(MusicLevel.QUIET, MusicLevel.LOW),
        ducking=(DuckingStrength.STRONG, DuckingStrength.MEDIUM),
        max_sfx=0,
    ),
    Recipe(
        name=AutoEditRecipe.MINIMAL,
        version="minimal_v1",
        label="Minimal",
        description="Speaker first: minimal captions, original sound, almost nothing added.",
        intent=(
            "Clean speaker-first output. Minimal captions, the original audio first, at most "
            "one visual, a hook only if it really helps, music only very quietly."
        ),
        smart_reframe_confidence=(ReframeConfidence.HIGH,),
        caption_presets=(DynamicPreset.MINIMAL,),
        caption_positions=(CaptionPosition.BOTTOM,),
        hook_allowed=True,
        hook_styles=(HookStyle.MINIMAL,),
        hook_seconds=1.5,
        hook_max_seconds=2.0,
        max_visuals=1,
        visual_modes=(VisualMode.CUTAWAY,),
        cutaway_fit=VisualFit.FILL,
        pip_position=VisualPosition.TOP_RIGHT,
        transition=VisualTransition.FADE,
        transition_seconds=0.3,
        min_visual_seconds=2.0,
        min_gap_seconds=4.0,
        music_levels=(MusicLevel.QUIET,),
        ducking=(DuckingStrength.STRONG,),
        max_sfx=0,
    ),
)

RECIPES_BY_VERSION: dict[str, Recipe] = {recipe.version: recipe for recipe in _RECIPES}
CURRENT_RECIPES: dict[AutoEditRecipe, Recipe] = {recipe.name: recipe for recipe in _RECIPES}
RECIPE_ORDER: tuple[AutoEditRecipe, ...] = tuple(recipe.name for recipe in _RECIPES)


def current_recipe(name: str | AutoEditRecipe) -> Recipe:
    """Today's version of a recipe (ValueError for anything outside the allow-list)."""
    return CURRENT_RECIPES[AutoEditRecipe(name)]


def recipe_version(version: str) -> Recipe:
    """The exact recipe a plan was made with (ValueError if this server does not know it)."""
    try:
        return RECIPES_BY_VERSION[version]
    except KeyError:
        raise ValueError("Unknown recipe version") from None
