"""Untrusted B-roll proposals are checked strictly (nothing clamped or invented), duplicates of
the same idea collapse, overlaps keep the stronger suggestion, and density stays restrained."""

import math

import pytest

from app.services.broll.validation import (
    MAX_SUGGESTION_SECONDS,
    MIN_SUGGESTION_SECONDS,
    RawSuggestion,
    max_suggestions,
    query_words,
    validate_suggestions,
)


def raw(
    start=3.2, end=5.8, query="Moon / spacecraft footage", reason="Mentions the Moon", score=80
):
    return RawSuggestion(start=start, end=end, query=query, reason=reason, score=score)


def test_a_good_suggestion_is_kept_rounded_and_cleaned():
    report = validate_suggestions(
        [raw(start=3.2049, end=5.8, query='  "Moon   landing"  ', reason=" The  Moon line ")], 30.0
    )
    assert [(s.start, s.end, s.query, s.reason, s.score) for s in report.kept] == [
        (3.2, 5.8, "Moon landing", "The Moon line", 80)
    ]
    assert report.rejected_count == 0


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (raw(start="3"), "invalid_time"),
        (raw(end=math.nan), "invalid_time"),
        (raw(start=True), "invalid_time"),
        (raw(start=-0.1), "outside_clip"),
        (raw(start=27.0, end=30.5), "outside_clip"),  # ends after the clip: never clamped
        (raw(start=5.0, end=4.0), "outside_clip"),
        (raw(start=3.0, end=3.0 + MIN_SUGGESTION_SECONDS - 0.01), "bad_length"),
        (raw(start=3.0, end=3.0 + MAX_SUGGESTION_SECONDS + 0.01), "bad_length"),  # never trimmed
        (raw(query=""), "invalid_text"),
        (raw(query="   "), "invalid_text"),
        (raw(query=42), "invalid_text"),
        (raw(query="x" * 121), "invalid_text"),
        (raw(query="the footage"), "invalid_text"),  # no subject left
        (raw(reason=None), "invalid_text"),
        (raw(reason="r" * 301), "invalid_text"),
        (raw(score=101), "invalid_score"),
        (raw(score=-5), "invalid_score"),
        (raw(score=85.5), "invalid_score"),
        (raw(score="90"), "invalid_score"),
        (raw(score=True), "invalid_score"),
    ],
)
def test_bad_proposals_are_rejected_not_repaired(item, reason):
    report = validate_suggestions([item], 30.0)
    assert report.kept == [] and report.rejected == {reason: 1}


def test_whole_number_floats_and_missing_scores_are_accepted():
    report = validate_suggestions(
        [raw(score=85.0), raw(start=12, end=14, query="rocket", score=None)], 30
    )
    assert [s.score for s in report.kept] == [85, None]


def test_equivalent_queries_for_the_same_moment_collapse_into_the_strongest():
    report = validate_suggestions(
        [
            raw(start=3.0, end=5.0, query="moon", score=60),
            raw(start=3.5, end=5.5, query="the Moon", score=90),
            raw(start=6.0, end=8.0, query="Moon footage", score=70),  # within the 2 s window
        ],
        30.0,
    )
    assert [(s.query, s.score) for s in report.kept] == [("the Moon", 90)]
    assert report.rejected == {"duplicate": 2}


def test_the_same_idea_much_later_is_a_new_moment():
    report = validate_suggestions(
        [raw(start=3, end=5, query="moon"), raw(start=20, end=22, query="the Moon")], 30.0
    )
    assert len(report.kept) == 2


def test_overlapping_different_ideas_keep_the_stronger_one():
    report = validate_suggestions(
        [
            raw(start=3, end=6, query="rocket", score=50),
            raw(start=5, end=8, query="astronaut", score=75),
        ],
        30.0,
    )
    assert [s.query for s in report.kept] == ["astronaut"] and report.rejected == {"overlap": 1}


def test_density_is_capped_by_clip_length_keeping_the_strongest_in_time_order():
    items = [
        raw(start=i * 3.0, end=i * 3.0 + 2.0, query=f"thing{i}", score=10 + i) for i in range(10)
    ]
    report = validate_suggestions(items, 30.0)
    assert max_suggestions(30.0) == 4
    assert [s.query for s in report.kept] == ["thing6", "thing7", "thing8", "thing9"]
    assert report.rejected == {"density": 6}


@pytest.mark.parametrize(("duration", "cap"), [(5, 1), (14, 2), (30, 4), (60, 8), (600, 8)])
def test_density_cap(duration, cap):
    assert max_suggestions(duration) == cap


def test_results_are_deterministic_for_ties():
    items = [
        raw(start=3, end=5, query="moon", score=70),
        raw(start=4, end=6, query="rocket", score=70),
    ]
    first = validate_suggestions(items, 30.0).kept
    assert first == validate_suggestions(list(reversed(items)), 30.0).kept
    assert [s.query for s in first] == ["moon"]


def test_query_words_ignore_the_medium_and_simple_plurals():
    assert query_words("Moon / spacecraft footage") == {"moon", "spacecraft"}
    assert query_words("Rockets launching") == {"rocket", "launching"}
    assert query_words("close-up shots of glass") == {"glass"}


def test_an_unusable_clip_duration_keeps_nothing():
    report = validate_suggestions([raw()], 0.0)
    assert report.kept == [] and report.rejected == {"outside_clip": 1}
