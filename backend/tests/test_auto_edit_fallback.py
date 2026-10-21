"""The deterministic Auto Edit planner and the honest fallback: conservative rules inside the
recipe, the same plan for the same context, and the fallback standing in only when the model
cannot answer (never hiding a configuration mistake)."""

from dataclasses import replace

import pytest

from app.core.config import Settings, get_settings
from app.services.auto_edit.contract import (
    AudioOption,
    BrollOption,
    Capabilities,
    PlannerConfigurationError,
    PlannerOutputError,
    PlannerResult,
    PlannerTimeoutError,
    PlannerUnavailableError,
    VisualOption,
    parse_proposal,
)
from app.services.auto_edit.fallback import (
    FALLBACK_MODEL,
    FALLBACK_PROVIDER,
    FallbackAutoEditPlanner,
)
from app.services.auto_edit.planners import get_planner, plan, planner_model
from app.services.auto_edit.recipes import CURRENT_RECIPES, current_recipe
from tests.test_auto_edit_contract import GOOD, context

CAPS = Capabilities(
    smart_reframe=True, reframe_confidence="high", word_timing=True, phrase_timing=True,
    text_overlays=True, visuals=True,
)  # fmt: skip
NOTHING = Capabilities(
    smart_reframe=False, reframe_confidence=None, word_timing=False, phrase_timing=False,
    text_overlays=True, visuals=True,
)  # fmt: skip
BRIDGE = VisualOption(
    "visual_asset_1", "image", "toothpick-bridge.jpg", "", ("bridge",), "landscape"
)
SHORT_VIDEO = VisualOption("visual_asset_2", "video", "joint.mp4", "", ("joint",), "landscape", 1.0)
JOINT = BrollOption(
    "suggestion_1", 10.2, 12.7, "bridge joint", "The lesson", ("visual_asset_1",),
    strong_matches=("visual_asset_1",),
)  # fmt: skip


def fallback(recipe="punchy", **overrides):
    fields = {
        "recipe": current_recipe(recipe).summary(),
        "capabilities": CAPS,
        "broll": (JOINT,),
        "visual_assets": (BRIDGE,),
        "music": None,
        "sound_effects": (),
        **overrides,
    }
    return FallbackAutoEditPlanner().plan(context(**fields)).proposal


def test_a_complete_conservative_plan():
    proposal = fallback()
    assert proposal.layout.mode == "smart_reframe"
    assert proposal.captions.enabled and proposal.captions.preset == "punch"
    assert proposal.captions.position == "bottom"
    assert proposal.hook.enabled and proposal.hook.text == "Our bridge collapsed"
    assert proposal.hook.style == "headline" and proposal.hook.duration_seconds == 2.0
    assert [v.model_dump() for v in proposal.visuals] == [
        {"suggestion": "suggestion_1", "asset": "visual_asset_1", "mode": "cutaway"}
    ]
    assert proposal.audio.use_music is False and proposal.audio.transition_sounds is False
    assert all(len(text) <= 200 for text in proposal.explanations.model_dump().values())


def test_the_same_context_gives_the_same_plan():
    assert fallback() == fallback()


@pytest.mark.parametrize(
    ("recipe", "confidence", "orientation", "expected"),
    [
        ("punchy", "mixed", "landscape", "smart_reframe"),  # Punchy accepts mixed framing
        ("clean", "mixed", "landscape", "blur_background"),  # Clean needs high confidence
        ("minimal", "fallback", "landscape", "blur_background"),
        ("story", "high", "portrait", "smart_reframe"),
    ],
)
def test_framing_follows_confidence_and_recipe(recipe, confidence, orientation, expected):
    caps = replace(CAPS, reframe_confidence=confidence)
    assert (
        fallback(recipe, capabilities=caps, source_orientation=orientation).layout.mode == expected
    )


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [("landscape", "blur_background"), ("portrait", "center_crop"), ("square", "center_crop")],
)
def test_without_framing_the_source_geometry_decides(orientation, expected):
    proposal = fallback(capabilities=NOTHING, source_orientation=orientation)
    assert proposal.layout.mode == expected


def test_captions_need_transcript_timing():
    phrase_only = replace(CAPS, word_timing=False)
    assert fallback(capabilities=phrase_only).captions.enabled
    proposal = fallback(capabilities=NOTHING)
    assert not proposal.captions.enabled
    assert "no transcript timing" in proposal.explanations.captions


@pytest.mark.parametrize("hook", [None, "", "x" * 61])
def test_the_hook_is_the_candidates_own_or_nothing(hook):
    proposal = fallback(candidate_hook=hook)
    assert not proposal.hook.enabled and proposal.hook.text == ""


def test_the_hook_is_never_rewritten():
    assert fallback(candidate_hook="  Our   bridge\ncollapsed ").hook.text == "Our bridge collapsed"


def test_no_hook_without_text_overlays():
    caps = replace(CAPS, text_overlays=False)
    proposal = fallback(capabilities=caps)
    assert not proposal.hook.enabled and not proposal.captions.enabled


def test_visuals_need_a_strong_match():
    weak = replace(JOINT, strong_matches=())
    proposal = fallback(broll=(weak,))
    assert proposal.visuals == []
    assert "No project visual strongly matched" in proposal.explanations.visuals


def test_visuals_respect_the_recipe_hold_and_the_video_length():
    short_moment = replace(JOINT, start=10.0, end=11.5)  # 1.5 s < Story's 2 s hold
    assert fallback("story", broll=(short_moment,)).visuals == []
    video_only = replace(JOINT, matches=("visual_asset_2",), strong_matches=("visual_asset_2",))
    assert fallback(broll=(video_only,), visual_assets=(SHORT_VIDEO,)).visuals == []


def test_at_most_one_visual_and_never_without_suggestions():
    second = replace(JOINT, handle="suggestion_2", start=13.0, end=15.0)
    assert len(fallback(broll=(JOINT, second)).visuals) == 1
    proposal = fallback(broll=())
    assert proposal.visuals == [] and "no B-roll suggestions" in proposal.explanations.visuals
    assert fallback(capabilities=replace(CAPS, visuals=False)).visuals == []


def test_music_only_from_an_explicit_choice_at_the_quietest_level():
    music = AudioOption("music_1", "calm.mp3", 40.0)
    proposal = fallback("clean", music=music)
    assert proposal.audio.use_music and proposal.audio.music_level == "quiet"
    assert proposal.audio.ducking == "medium"
    assert not fallback("clean").audio.use_music


def test_never_sound_effects():
    whoosh = AudioOption("sfx_1", "whoosh.wav", 0.8, transition=True)
    assert not fallback("punchy", sound_effects=(whoosh,)).audio.transition_sounds


@pytest.mark.parametrize("recipe", list(CURRENT_RECIPES))
def test_every_recipe_plans_an_empty_clip(recipe):
    proposal = fallback(
        recipe.value, capabilities=NOTHING, broll=(), visual_assets=(), lines=(),
        candidate_hook=None,
    )  # fmt: skip
    assert proposal.layout.mode == "blur_background" and proposal.visuals == []
    assert not proposal.hook.enabled and not proposal.captions.enabled
    assert proposal.captions.preset == current_recipe(recipe).caption_presets[0].value


# --- falling back honestly --------------------------------------------------------------------


class Failing:
    name, model = "ollama", "llama3.2:3b"

    def __init__(self, error):
        self.error = error

    def plan(self, ctx):
        raise self.error


class Working:
    name, model = "ollama", "llama3.2:3b"

    def plan(self, ctx):
        return PlannerResult(parse_proposal(GOOD, provider="model"), self.name, self.model)


@pytest.mark.parametrize(
    "error",
    [PlannerUnavailableError("down"), PlannerTimeoutError("slow"), PlannerOutputError("junk")],
)
def test_the_rules_stand_in_when_the_model_cannot_answer(error):
    outcome = plan(context(), Failing(error), fallback_enabled=True)
    assert outcome.fallback_reason == error.code
    assert outcome.result.provider == FALLBACK_PROVIDER and outcome.result.model == FALLBACK_MODEL


def test_without_the_fallback_the_failure_is_reported():
    with pytest.raises(PlannerUnavailableError):
        plan(context(), Failing(PlannerUnavailableError("down")), fallback_enabled=False)


def test_a_configuration_mistake_is_never_hidden():
    with pytest.raises(PlannerConfigurationError):
        plan(context(), Failing(PlannerConfigurationError("no model")), fallback_enabled=True)


def test_a_working_model_is_used_as_is():
    outcome = plan(context(), Working(), fallback_enabled=True)
    assert outcome.fallback_reason is None and outcome.result.provider == "ollama"


def test_the_rules_can_be_the_configured_planner():
    settings = Settings(**{**get_settings().model_dump(), "auto_edit_planner_provider": "fallback"})
    assert planner_model(settings) == FALLBACK_MODEL
    planner = get_planner(settings, FALLBACK_PROVIDER, FALLBACK_MODEL)
    outcome = plan(context(), planner, fallback_enabled=True)
    assert outcome.fallback_reason is None and outcome.result.provider == FALLBACK_PROVIDER
