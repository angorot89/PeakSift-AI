"""Creator insights: a deterministic engine over one creator's own comparable shorts —
minimum samples on both sides, medians, effect, consistency and stability checks, observational
wording only — persisted per creator and source, recomputed only when inputs change, dismissals
kept, evidence limited to the creator's own shorts."""

import random
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api import performance as api
from app.models import InsightSet
from app.services.performance.insights import (
    MAX_INSIGHTS,
    MIN_SAMPLE,
    Short,
    features,
    find_patterns,
)
from tests.performance_fixtures import (
    NOW,
    analytics_settings,
    make_content,
    provenance,
    signed_in_creator,
    with_week,
)

FORBIDDEN = re.compile(
    r"\b(will|viral|best|guarantee\w*|because|caus\w*|predict\w*|always)\b", re.I
)


def short(value: float, retention: float = 50.0, **feature_values) -> Short:
    base = {"captions": "on", "hook": "no_hook", "made_with": "editor", "length": "under_20s"}
    return Short(uuid.uuid4(), datetime(2026, 9, 1, tzinfo=UTC), {**base, **feature_values},
                 {"engaged_views": value, "average_view_percentage": retention})  # fmt: skip


def hooks(with_hook: list[float], without: list[float]) -> list[Short]:
    return [short(v, hook="with_hook") for v in with_hook] + [short(v) for v in without]


# --- features ---------------------------------------------------------------------------------


def test_features_come_from_the_normalized_provenance():
    found = features(provenance(captions="punch", hook=True, auto=True), 25.0)
    assert found == {"made_with": "auto_edit", "recipe": "punchy", "layout": "center_crop",
                     "captions": "on", "caption_style": "punch", "hook": "with_hook",
                     "visuals": "no_visuals", "music": "no_music", "length": "20_to_40s",
                     "clip_category": "story"}  # fmt: skip
    assert features({}, None) == {}  # nothing known: nothing compared
    assert features(provenance(captions=None), 45)["captions"] == "off"
    assert "caption_style" not in features(provenance(captions=None), 45)


# --- the engine -------------------------------------------------------------------------------


def test_a_clear_consistent_pattern_is_reported_with_observational_wording():
    shorts = hooks([200, 210, 190, 220, 205, 230], [100, 105, 95, 110, 98, 102])
    [finding] = [f for f in find_patterns(shorts) if f.metric == "engaged_views"]
    assert (finding.feature, finding.value, finding.direction) == ("hook", "with_hook", "higher")
    assert (len(finding.group), len(finding.comparison)) == (6, 6)
    assert finding.group_median == 207.5 and finding.comparison_median == 101.0
    assert finding.consistency == 1.0 and finding.confidence == "limited"
    assert finding.statement == (
        "In your recent uploads, shorts with an opening hook have tended to get more engaged "
        "views in their first week: median 208 vs 101 for your other shorts (6 vs 6 shorts)."
    )
    assert not FORBIDDEN.search(finding.statement)


def test_too_few_shorts_overall_or_on_one_side_say_nothing():
    assert find_patterns(hooks([200] * 5, [100] * 4)) == []  # 9 < MIN_SAMPLE
    assert find_patterns(hooks([200] * 4, [100] * 8)) == []  # only 4 with a hook


def test_small_differences_are_not_patterns():
    assert find_patterns(hooks([115] * 6, [100] * 6)) == []  # 15% < 20%


def test_one_outlier_is_not_a_pattern():
    # The median moves, but most shorts with a hook did no better: inconsistent.
    shorts = hooks([5000, 4000, 130, 95, 90, 98], [100, 105, 95, 110, 98, 102])
    assert [f for f in find_patterns(shorts) if f.feature == "hook"] == []


def test_a_pattern_resting_on_one_short_is_not_kept():
    # Leaving out one of the three 130s drops the hook median to 110: not a pattern, either way
    # it is phrased (with a hook higher, or without one lower).
    shorts = hooks([130, 130, 130, 90, 90], [100, 100, 100, 100, 100, 100, 100])
    assert [f for f in find_patterns(shorts) if f.feature == "hook"] == []


def test_lower_figures_are_reported_too():
    [finding] = [f for f in find_patterns(hooks([50, 55, 45, 52, 48, 51], [100] * 6))
                 if f.metric == "engaged_views"]  # fmt: skip
    assert finding.direction == "lower"
    assert "have tended to get fewer engaged views" in finding.statement


def test_with_and_without_are_one_pattern_not_two():
    found = find_patterns(hooks([200] * 6, [100] * 6))
    hook_views = [f for f in found if f.feature == "hook" and f.metric == "engaged_views"]
    assert len(hook_views) == 1


def test_retention_patterns_use_percent_wording():
    shorts = [short(100, 70, hook="with_hook") for _ in range(6)] + [
        short(100, 40) for _ in range(6)
    ]
    [finding] = [f for f in find_patterns(shorts) if f.metric == "average_view_percentage"]
    assert "watched for a larger share of their length" in finding.statement
    assert "median 70% vs 40%" in finding.statement


def test_at_most_five_and_the_largest_first_and_deterministic():
    rng = random.Random(7)
    shorts = []
    for n in range(24):
        flags = {f"f{k}": "on" if (n >> k) & 1 else "off" for k in range(4)}
        base = 100 * (1.5 ** sum((n >> k) & 1 for k in range(4)))
        shorts.append(Short(uuid.UUID(int=n), datetime(2026, 9, 1, tzinfo=UTC),
                            {"captions": flags["f0"],
                             "hook": "with_hook" if (n >> 1) & 1 else "no_hook",
                             "music": "with_music" if (n >> 2) & 1 else "no_music",
                             "visuals": "with_visuals" if (n >> 3) & 1 else "no_visuals"},
                            {"engaged_views": base * rng.uniform(0.95, 1.05),
                             "average_view_percentage": 50.0}))  # fmt: skip
    found = find_patterns(shorts)
    assert 1 <= len(found) <= MAX_INSIGHTS
    effects = [abs(f.effect) for f in found]
    assert effects == sorted(effects, reverse=True)
    assert [f.rank for f in found] == list(range(1, len(found) + 1))
    shuffled = shorts[:]
    random.Random(1).shuffle(shuffled)
    assert [f.key for f in find_patterns(shuffled)] == [f.key for f in found]


def test_confidence_is_moderate_at_most():
    found = find_patterns(hooks([200] * 8, [100] * 8))
    assert {f.confidence for f in found} == {"moderate"}


# --- persisted, through the API ---------------------------------------------------------------


@pytest.fixture
def settings(monkeypatch):
    configured = analytics_settings()
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


def library(db, user, edit, pattern: list[tuple[bool, int]]):
    contents = []
    for n, (hook, engaged) in enumerate(pattern):
        content = make_content(db, user, edit, published_at=NOW - timedelta(days=12 + n),
                               provenance=provenance(hook=hook), title=f"Short {n}")  # fmt: skip
        contents.append(with_week(db, content, engaged))
    return contents


HOOK_PATTERN = [(True, 200 + n) for n in range(6)] + [(False, 100 + n) for n in range(6)]


def test_insights_are_computed_once_and_shown_with_evidence(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    contents = library(db_session, user, edit, HOOK_PATTERN)
    body = client.get("/performance/insights").json()
    assert body["status"] == "ready" and body["sample_size"] == 12 and body["simulated"] is True
    assert body["minimum_sample"] == MIN_SAMPLE and body["minimum_group"] == 5
    [insight] = [i for i in body["insights"] if i["metric"] == "engaged_views"]
    assert insight["feature"] == "hook" and insight["direction"] == "higher"
    assert {s["title"] for s in insight["group"]} == {f"Short {n}" for n in range(6)}
    assert not FORBIDDEN.search(insight["statement"])
    computed = body["computed_at"]
    assert client.get("/performance/insights").json()["computed_at"] == computed  # unchanged
    with_week(db_session, make_content(db_session, user, edit, published_at=NOW - timedelta(40),
                                       provenance=provenance()), 100)  # fmt: skip
    assert client.get("/performance/insights").json()["sample_size"] == 13
    assert len(contents) == 12


def test_too_few_shorts_is_no_reliable_pattern_yet(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    library(db_session, user, edit, HOOK_PATTERN[:9])
    body = client.get("/performance/insights").json()
    assert body["status"] == "insufficient" and body["insights"] == []


def test_a_dismissal_survives_recomputation(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    library(db_session, user, edit, HOOK_PATTERN)
    insight = client.get("/performance/insights").json()["insights"][0]
    assert client.post(f"/performance/insights/{insight['id']}/dismiss").json()["dismissed"]
    with_week(db_session, make_content(db_session, user, edit, published_at=NOW - timedelta(40),
                                       provenance=provenance()), 101)  # fmt: skip
    again = {(i["feature"], i["value"], i["metric"]): i
             for i in client.get("/performance/insights").json()["insights"]}  # fmt: skip
    restored = again[(insight["feature"], insight["value"], insight["metric"])]
    assert restored["dismissed"] is True and restored["id"] != insight["id"]
    assert (
        client.post(f"/performance/insights/{restored['id']}/restore").json()["dismissed"] is False
    )


def test_insights_are_private_to_their_creator(client, db_session, settings):
    owner, edit = signed_in_creator(db_session, client)
    library(db_session, owner, edit, HOOK_PATTERN)
    insight = client.get("/performance/insights").json()["insights"][0]
    signed_in_creator(db_session, client)
    assert client.post(f"/performance/insights/{insight['id']}/dismiss").status_code == 404
    mine = client.get("/performance/insights").json()
    assert mine["sample_size"] == 0 and mine["insights"] == []
    assert db_session.query(InsightSet).count() == 2  # one per creator, never shared


def test_simulated_and_real_data_get_separate_sets(client, db_session, settings, monkeypatch):
    user, edit = signed_in_creator(db_session, client)
    library(db_session, user, edit, HOOK_PATTERN)
    assert client.get("/performance/insights").json()["sample_size"] == 12
    real = analytics_settings(performance_provider="youtube")
    monkeypatch.setattr(api, "get_settings", lambda: real)
    body = client.get("/performance/insights").json()
    assert body["source"] == "youtube" and body["sample_size"] == 0 and not body["simulated"]
