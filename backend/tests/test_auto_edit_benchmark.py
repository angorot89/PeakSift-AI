"""The Auto Edit quality check, automated where the measure is objective: every case × recipe
gives a valid configuration, no invented or mismatched asset survives, hooks are grounded,
visuals appear exactly where a matching asset exists, effect density stays within the recipe,
music only from an explicit choice — and an adversarial model's inventions are removed. No
score is computed; creative quality is reviewed by people."""

import json

import pytest

from app.services.auto_edit.benchmark import CASES, evaluate
from app.services.auto_edit.contract import PlannerResult, parse_proposal
from app.services.auto_edit.fallback import FallbackAutoEditPlanner
from app.services.auto_edit.ollama import constraints, user_prompt
from app.services.auto_edit.recipes import RECIPE_ORDER, current_recipe
from tests.test_auto_edit_contract import UUID

GRID = [(case, recipe.value) for case in CASES for recipe in RECIPE_ORDER]
IDS = [f"{case.name}-{recipe}" for case, recipe in GRID]


def test_six_representative_cases():
    assert [c.name for c in CASES] == [
        "energetic_stream", "explainer", "podcast", "quiet_commentary", "no_useful_broll",
        "useful_broll_with_asset",
    ]  # fmt: skip


@pytest.mark.parametrize(("case", "recipe"), GRID, ids=IDS)
def test_the_rules_make_a_sound_plan_for_every_case(case, recipe):
    report = evaluate(case, recipe, FallbackAutoEditPlanner())
    bounds = current_recipe(recipe)
    assert report.valid and report.planner == "fallback" and report.fallback_reason is None
    assert report.hallucinated == 0 and report.degraded == 0
    assert report.hook_grounded in (True, None)
    assert (report.visuals > 0) == case.expects_visual
    if report.visuals:
        assert report.visual_relevance == 1.0
    assert report.visuals <= min(1, bounds.max_visuals)  # the rules add at most one
    assert report.sound_effects == 0
    assert report.music == case.music
    ceiling = (bounds.max_visuals + bounds.max_sfx) / case.duration * 10
    assert report.effect_density <= round(ceiling, 2) + 0.01  # reported to two decimals


class Adversarial:
    """A model that ignores every rule: invented handles, unavailable features, wild hooks."""

    name, model = "ollama", "adversarial"

    def plan(self, context):
        data = {
            "layout": {"mode": "smart_reframe"},
            "captions": {"enabled": True, "preset": "boxed", "position": "top"},
            "hook": {"enabled": True, "text": "SpaceX paid us 1000000 dollars for this",
                     "style": "boxed", "duration_seconds": 9},
            "visuals": [
                {"suggestion": "suggestion_7", "asset": "visual_asset_9", "mode": "cutaway"},
                {"suggestion": "suggestion_1", "asset": "visual_asset_4", "mode": "pip"},
            ],
            "audio": {"use_music": True, "music_level": "medium", "ducking": "light",
                      "transition_sounds": True},
            "explanations": {"layout": "x", "captions": "x", "hook": "x", "visuals": "x",
                             "audio": "x"},
        }  # fmt: skip
        return PlannerResult(parse_proposal(data, provider="test"), self.name, self.model)


@pytest.mark.parametrize(("case", "recipe"), GRID, ids=IDS)
def test_an_adversarial_model_is_contained(case, recipe):
    report = evaluate(case, recipe, Adversarial())
    assert report.valid
    assert report.hallucinated >= 1  # counted, and removed:
    assert report.visuals == 0 and report.sound_effects == 0
    assert report.hook in (None, case.candidate_hook)  # never the invented claim
    assert report.music == case.music  # only ever the creator's own track
    assert report.degraded >= 2


def test_the_prompt_states_each_clips_constraints_without_ids():
    by_name = {case.name: case for case in CASES}
    podcast = constraints(by_name["podcast"].context("minimal"))
    assert "Smart Reframe is NOT available: use blur_background or center_crop." in podcast
    assert "No B-roll suggestion has a strong matching asset: visuals must be []." in podcast
    assert "No music track was chosen: use_music must be false." in podcast
    assert "Transition sounds are not available: transition_sounds must be false." in podcast
    useful = constraints(by_name["useful_broll_with_asset"].context("punchy"))
    assert "Smart Reframe is available: prefer it." in useful
    assert any("suggestion_1 with visual_asset_1" in rule for rule in useful)
    assert not any("use_music must be false" in rule for rule in useful)  # a track was chosen
    assert not any("transition_sounds must be false" in rule for rule in useful)
    for case in CASES:
        assert not UUID.search(user_prompt(case.context("story")))


def test_rows_are_plain_data():
    row = evaluate(CASES[0], "clean", FallbackAutoEditPlanner()).row()
    assert json.loads(json.dumps(row)) == row
    assert not {"score", "quality", "viral"} & set(row)
