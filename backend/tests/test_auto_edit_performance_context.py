# ruff: noqa: F811 - the fake_queues fixture imported from test_auto_edit_api is a parameter here
"""Auto Edit with patterns from the creator's own shorts: only on request, symbolic hints about
choices a planner makes (never music, ids or titles), the recipe first, a conservative rules
planner that names each hint it used, unchanged V1.2 snapshots and fingerprints without it."""

import re
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.api import auto_edit as api
from app.models import AutoEditPlan
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.fallback import FallbackAutoEditPlanner
from app.services.auto_edit.ollama import constraints
from app.services.auto_edit.recipes import current_recipe
from app.services.performance.profile import PLANNER_FEATURES, creator_profile, favours
from tests.performance_fixtures import (
    NOW,
    analytics_settings,
    make_content,
    provenance,
    with_week,
)
from tests.test_auto_edit_api import clip_ctx, fake_queues  # noqa: F401 - fixture
from tests.test_auto_edit_contract import context
from tests.test_auto_edit_fallback import BRIDGE, CAPS, JOINT
from tests.test_clip_edit_api import sign_up

FORBIDDEN = re.compile(r"\b(will|viral|best|guarantee\w*|because|caus\w*|predict\w*)\b", re.I)


def hint(feature, value, direction="higher", confidence="limited"):
    return {"feature": feature, "value": value, "metric": "engaged_views", "direction": direction,
            "confidence": confidence, "group_size": 6, "comparison_size": 6,
            "text": f"Your shorts {feature}={value} …"}  # fmt: skip


def rules(*hints, recipe="punchy", **overrides):
    fields = {"recipe": current_recipe(recipe).summary(), "capabilities": CAPS, "broll": (JOINT,),
              "visual_assets": (BRIDGE,), "music": None, "sound_effects": (),
              "performance_hints": tuple(hints), **overrides}  # fmt: skip
    return FallbackAutoEditPlanner().plan(context(**fields)).proposal


# --- the request snapshot ----------------------------------------------------------------------


def test_without_patterns_the_request_is_exactly_v12():
    settings = analytics_settings()
    plain = AutoEditRequest.from_settings(settings, recipe="punchy").snapshot()
    assert "performance_context" not in plain
    assert AutoEditRequest.from_snapshot(plain).performance_context is None  # old plans load
    profile = {"version": "performance_profile_v1", "hints": [hint("hook", "with_hook")]}
    used = AutoEditRequest.from_settings(settings, recipe="punchy", performance_context=profile)
    assert used.snapshot()["performance_context"] == profile
    assert AutoEditRequest.from_snapshot(used.snapshot()) == used


# --- what planners see -------------------------------------------------------------------------


def test_the_planner_sees_symbolic_hints_only_when_asked():
    assert "creator_history" not in context().planner_view()
    view = context(performance_hints=(hint("caption_style", "boxed"),)).planner_view()
    assert view["creator_history"] == [{
        "choice": "caption_style", "value": "boxed", "observed": "higher first-week engaged views",
        "evidence": "limited (6 vs 6 earlier shorts)",
    }]  # fmt: skip
    assert "text" not in str(view["creator_history"])  # product copy stays out of prompts


def test_the_model_is_told_hints_are_weak_and_the_recipe_comes_first():
    assert not any("creator_history" in r for r in constraints(context()))
    [rule] = [r for r in constraints(context(performance_hints=(hint("hook", "no_hook"),)))
              if "creator_history" in r]  # fmt: skip
    assert "weak evidence, not rules" in rule and "the recipe and this clip come first" in rule


# --- the conservative rules planner ------------------------------------------------------------


def test_no_hints_give_exactly_the_old_plan():
    assert rules() == rules(hint("music", "with_music"), hint("length", "under_20s"))


def test_a_favoured_caption_style_inside_the_recipe_is_used_and_named():
    proposal = rules(hint("caption_style", "boxed"))
    assert proposal.captions.preset == "boxed"
    assert "“boxed” style" in proposal.explanations.captions
    assert "limited evidence" in proposal.explanations.captions
    assert not FORBIDDEN.search(proposal.explanations.captions)


def test_a_style_outside_the_recipe_is_ignored():
    assert rules(hint("caption_style", "focus")).captions.preset == "punch"


@pytest.mark.parametrize("found", [hint("hook", "no_hook"), hint("hook", "with_hook", "lower")])
def test_no_hook_when_shorts_without_one_did_better(found):
    proposal = rules(found)
    assert not proposal.hook.enabled and "without one have tended" in proposal.explanations.hook


def test_a_favoured_hook_changes_nothing_extra():
    assert rules(hint("hook", "with_hook")).hook == rules().hook


@pytest.mark.parametrize(
    "found", [hint("visuals", "no_visuals"), hint("visuals", "with_visuals", "lower")]
)
def test_no_cutaway_when_shorts_without_visuals_did_better(found):
    proposal = rules(found)
    assert proposal.visuals == [] and "without added visuals" in proposal.explanations.visuals


def test_captions_and_framing_are_never_changed_by_a_hint():
    proposal = rules(hint("captions", "off"), hint("captions", "on", "lower"),
                     hint("layout", "center_crop"))  # fmt: skip
    assert proposal.captions.enabled and proposal.layout.mode == "smart_reframe"


def test_favours_reads_both_phrasings():
    hints = [hint("hook", "with_hook", "lower")]
    assert favours(hints, "hook", "no_hook") is hints[0]
    assert favours(hints, "hook", "with_hook") is None
    assert favours([hint("layout", "fit", "lower")], "layout", "blur_background") is None


# --- the profile --------------------------------------------------------------------------------


def library(db, user, clip, pattern):
    owner = SimpleNamespace(clip=clip, clip_id=clip.id)
    for n, (with_hook, engaged) in enumerate(pattern):
        content = make_content(
            db, user, owner, published_at=NOW - timedelta(days=12 + n),
            provenance=provenance(hook=with_hook), title=f"Short {n}",
        )  # fmt: skip
        with_week(db, content, engaged)


HOOKLESS_BETTER = [(True, 100 + n) for n in range(6)] + [(False, 220 + n) for n in range(6)]


@pytest.fixture
def settings(monkeypatch):
    configured = analytics_settings()
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


def test_the_profile_keeps_planner_choices_never_ids_or_titles(client, db_session, settings):
    sign_up(client)
    ctx = clip_ctx(db_session)
    user = ctx["clip"].video.project.owner
    assert creator_profile(db_session, user.id, "fake") is None
    library(db_session, user, ctx["clip"], HOOKLESS_BETTER)
    profile = creator_profile(db_session, user.id, "fake")
    assert profile["sample_size"] == 12
    assert {h["feature"] for h in profile["hints"]} <= set(PLANNER_FEATURES)
    [found] = [h for h in profile["hints"] if h["feature"] == "hook"]
    # Phrased by the first-listed value: shorts with a hook tended lower.
    assert (found["value"], found["direction"]) == ("with_hook", "lower")
    text = str(profile)
    assert "Short " not in text and str(user.id) not in text
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text)
    assert not FORBIDDEN.search(found["text"])


def test_planning_with_patterns_is_opt_in_and_a_separate_plan(client, db_session, settings,
                                                              fake_queues):  # fmt: skip
    sign_up(client)
    ctx = clip_ctx(db_session)
    library(db_session, ctx["clip"].video.project.owner, ctx["clip"], HOOKLESS_BETTER)
    available = client.get("/auto-edit/performance-context").json()
    assert available["available"] and available["simulated"] and available["sample_size"] == 12
    assert any("with an opening hook have tended to have lower" in t for t in available["hints"])
    plain = client.post(ctx["base"], json={"recipe": "punchy"}).json()
    assert plain["performance_hints"] is None
    informed = client.post(ctx["base"], json={"recipe": "punchy", "use_performance_context": True})
    assert informed.status_code == 201 and informed.json()["id"] != plain["id"]
    assert informed.json()["performance_hints"] == available["hints"]
    row = db_session.get(AutoEditPlan, uuid.UUID(informed.json()["id"]))
    assert row.config["performance_context"]["hints"][0]["feature"] in PLANNER_FEATURES
    again = client.post(ctx["base"], json={"recipe": "punchy", "use_performance_context": True})
    assert again.status_code == 200 and again.json()["id"] == informed.json()["id"]
    # "Try another plan" keeps the creator's choice.
    row.status, row.error_code, row.error_message = "failed", "planner_timeout", "Timed out"
    db_session.commit()
    regenerated = client.post(f"{ctx['base']}/{row.id}/regenerate").json()
    assert regenerated["generation"] == 2 and regenerated["performance_hints"]


def test_asking_without_patterns_plans_normally(client, db_session, settings, fake_queues):
    sign_up(client)
    ctx = clip_ctx(db_session)
    assert client.get("/auto-edit/performance-context").json() == {
        "available": False, "simulated": True, "sample_size": 0, "hints": []}  # fmt: skip
    body = client.post(ctx["base"], json={"recipe": "punchy", "use_performance_context": True})
    plain = client.post(ctx["base"], json={"recipe": "punchy"})
    assert body.json()["performance_hints"] is None
    assert plain.status_code == 200 and plain.json()["id"] == body.json()["id"]  # same inputs
