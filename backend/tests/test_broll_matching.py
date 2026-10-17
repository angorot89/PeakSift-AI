"""Matching suggestions to the creator's visual assets: names, descriptions and tags compared on
short stems, a minimum coverage, at most three, strongest first — offered, never placed."""

import uuid
from datetime import UTC, datetime, timedelta

from app.models import VisualAsset
from app.services.broll.matching import AssetTerms, likely_matches, match_score

NOW = datetime.now(UTC)


def asset(name: str, description: str = "", tags=(), age_minutes: int = 0) -> VisualAsset:
    return VisualAsset(
        id=uuid.uuid4(), display_name=name, description=description, tags=list(tags),
        created_at=NOW - timedelta(minutes=age_minutes),
    )  # fmt: skip


def test_names_descriptions_and_tags_are_read_as_words():
    terms = AssetTerms.of(
        asset(
            "moon-launch_final.v2.mp4",
            "NASA-style rocket launch footage",
            ["Rocket", "space station"],
        )
    )
    assert {"moon", "launch", "final"} <= terms.name and "mp4" not in terms.name
    assert {"rocket", "launch", "footag"} <= terms.description
    assert terms.tags == {"rocket", "space", "statio"}


def test_scores_weight_tags_over_names_over_descriptions():
    tagged = AssetTerms.of(asset("a.png", tags=["bridge"]))
    named = AssetTerms.of(asset("toothpick-bridge.jpg"))
    described = AssetTerms.of(asset("b.png", "a bridge made of toothpicks"))
    assert match_score("bridge", tagged) == 1.0
    assert match_score("bridge", named) == 0.9
    assert match_score("bridge", described) == 0.7
    assert match_score("toothpick bridge model", named) == 0.6  # 2 of 3 words, by name
    assert match_score("bridges collapsing", named) == 0.45  # plural still matches; half covered
    assert match_score("the footage", named) == 0.0  # no subject words


def test_likely_matches_need_enough_coverage_and_are_capped():
    library = [
        asset("toothpick-bridge.jpg", age_minutes=5),
        asset("bridge-wide.jpg", age_minutes=1),
        asset("bridge-side.png", tags=["model", "bridge"], age_minutes=9),
        asset("bridge-old.png", age_minutes=20),
        asset("moon-surface.jpg"),
    ]
    ids = {str(a.id): a.display_name for a in library}
    found = [ids[i] for i in likely_matches("bridge model", library)]
    # Only the tagged asset covers both words; "bridge" in a name alone covers 0.45 < 0.5.
    assert found == ["bridge-side.png"]
    found = [ids[i] for i in likely_matches("bridge", library)]
    assert found == [
        "bridge-side.png",
        "bridge-wide.jpg",
        "toothpick-bridge.jpg",
    ]  # tag, then newest
    assert likely_matches("solar fan", library) == []
    assert likely_matches("success", library) == []
