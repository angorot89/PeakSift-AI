"""Creator recipes: four curated intents, versioned, whose every bound is a value the existing
editor and renderer accept — so no recipe can ever ask for something PeakSift cannot render."""

import pytest

from app.models import AutoEditRecipe
from app.services.audio_mix.config import MUSIC_GAIN_DB, AudioMix
from app.services.auto_edit.recipes import (
    CURRENT_RECIPES,
    MUSIC_LEVEL_DB,
    RECIPE_ORDER,
    RECIPES_BY_VERSION,
    MusicLevel,
    current_recipe,
    recipe_version,
)
from app.services.clip_edit.config import EditConfig
from app.services.clip_edit.hook import MAX_HOOK_SECONDS, MIN_HOOK_SECONDS
from app.services.visuals.config import (
    TRANSITION_RANGE,
    VisualMode,
    VisualPosition,
    VisualsConfig,
)

ALL = list(CURRENT_RECIPES.values())


def test_exactly_four_curated_recipes_in_a_stable_order():
    assert RECIPE_ORDER == (
        AutoEditRecipe.CLEAN, AutoEditRecipe.PUNCHY, AutoEditRecipe.STORY, AutoEditRecipe.MINIMAL
    )  # fmt: skip
    assert {r.version for r in ALL} == {"clean_v1", "punchy_v1", "story_v1", "minimal_v1"}


def test_versions_are_unique_and_resolve_exactly():
    assert len(RECIPES_BY_VERSION) == len(ALL)
    for recipe in ALL:
        assert recipe_version(recipe.version) is recipe
        assert current_recipe(recipe.name.value) is recipe
        assert recipe.version.startswith(f"{recipe.name.value}_v")


@pytest.mark.parametrize("bad", ["viral", "", "PUNCHY"])
def test_unknown_recipes_are_refused(bad):
    with pytest.raises(ValueError):
        current_recipe(bad)


def test_unknown_versions_are_refused():
    with pytest.raises(ValueError):
        recipe_version("punchy_v99")


@pytest.mark.parametrize("recipe", ALL, ids=lambda r: r.version)
def test_every_caption_and_hook_choice_is_renderable(recipe):
    assert recipe.caption_presets and recipe.caption_positions
    for preset in recipe.caption_presets:
        for position in recipe.caption_positions:
            for style in recipe.hook_styles:
                hook_position = "center" if position.value == "top" else "top"
                EditConfig.create(
                    layout="blur_background", captions_enabled=True, caption_style=preset.value,
                    caption_position=position.value, caption_timing="phrase_fallback",
                    hook_enabled=True, hook_text="A grounded hook", hook_style=style.value,
                    hook_position=hook_position, hook_duration=recipe.hook_max_seconds,
                )  # fmt: skip
    assert MIN_HOOK_SECONDS <= recipe.hook_seconds <= recipe.hook_max_seconds <= MAX_HOOK_SECONDS


@pytest.mark.parametrize("recipe", ALL, ids=lambda r: r.version)
def test_every_visual_choice_is_renderable(recipe):
    assert 0 <= recipe.max_visuals <= 4
    assert VisualMode.OVERLAY not in recipe.visual_modes  # overlays stay a creator choice
    low, high = TRANSITION_RANGE
    assert low <= recipe.transition_seconds <= high
    # Insets never sit in the bottom corners, where the captions are.
    assert recipe.pip_position in (VisualPosition.TOP_LEFT, VisualPosition.TOP_RIGHT)
    for mode in recipe.visual_modes:
        element = {
            "asset_id": "00000000-0000-4000-8000-000000000001", "mode": mode.value,
            "start_seconds": 1.0, "end_seconds": 1.0 + max(recipe.min_visual_seconds, 1.0),
            "transition": recipe.transition.value,
            "transition_seconds": recipe.transition_seconds,
        }  # fmt: skip
        if mode == VisualMode.CUTAWAY:
            element["fit"] = recipe.cutaway_fit.value
        else:
            element["position"] = recipe.pip_position.value
        assert VisualsConfig.create({"elements": [element]}) is not None


@pytest.mark.parametrize("recipe", ALL, ids=lambda r: r.version)
def test_every_audio_choice_is_renderable(recipe):
    low, high = MUSIC_GAIN_DB
    assert recipe.ducking  # music, when chosen, is always ducked under speech
    for level in recipe.music_levels:
        assert low <= MUSIC_LEVEL_DB[level] <= high
        for ducking in recipe.ducking:
            mix = AudioMix.create({
                "music": {"asset_id": "00000000-0000-4000-8000-000000000002",
                          "gain_db": MUSIC_LEVEL_DB[level], "ducking": ducking.value},
            })  # fmt: skip
            assert mix is not None and mix.music.ducking == ducking


def test_recipes_differ_in_intent():
    clean, punchy = current_recipe("clean"), current_recipe("punchy")
    story, minimal = current_recipe("story"), current_recipe("minimal")
    assert punchy.max_visuals > clean.max_visuals > minimal.max_visuals
    assert punchy.max_sfx > 0 and clean.max_sfx == story.max_sfx == minimal.max_sfx == 0
    assert punchy.caption_presets[0].value == "punch"
    assert minimal.caption_presets == (minimal.caption_presets[0],)
    assert minimal.caption_presets[0].value == "minimal"
    assert story.visual_modes == (VisualMode.CUTAWAY,) and story.min_visual_seconds >= 2.0
    assert (
        max(MUSIC_LEVEL_DB[level] for level in minimal.music_levels)
        == MUSIC_LEVEL_DB[MusicLevel.QUIET]
    )


def test_the_planner_summary_is_bounds_only():
    summary = current_recipe("punchy").summary()
    assert summary["recipe"] == "punchy" and summary["sound_effects_allowed"] is True
    assert set(summary) == {
        "recipe", "intent", "caption_presets", "caption_positions", "hook_allowed",
        "hook_styles", "hook_max_seconds", "max_visuals", "visual_modes", "music_levels",
        "ducking", "sound_effects_allowed",
    }  # fmt: skip


@pytest.mark.parametrize("recipe", ALL, ids=lambda r: r.version)
def test_creator_copy_is_short(recipe):
    assert recipe.label and len(recipe.description) <= 90
