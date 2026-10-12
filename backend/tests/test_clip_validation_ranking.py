import pytest

from app.services.clip_detection.contract import AnalysisWindow, TranscriptLine
from app.services.clip_detection.ranking import (
    WEIGHTS,
    overall_score,
    overlap_ratio,
    rank_candidates,
)
from app.services.clip_detection.validation import (
    ValidatedCandidate,
    validate_candidates,
)
from tests.fakes import raw_candidate

# A 2-minute window at 600–720 s: 24 lines of 5 s.
LINES = tuple(
    TranscriptLine(start=600.0 + 5 * i, end=605.0 + 5 * i, text=f"line {i}") for i in range(24)
)
WINDOW = AnalysisWindow(index=3, start=600.0, end=720.0, lines=LINES)


def validate(*proposals, **overrides):
    options = {
        "window": WINDOW,
        "video_duration": 3600.0,
        "min_clip_seconds": 15.0,
        "max_clip_seconds": 60.0,
        "tolerance_seconds": 1.0,
    }
    options.update(overrides)
    return validate_candidates(proposals, **options)


def accepted(*proposals, **overrides) -> ValidatedCandidate:
    report = validate(*proposals, **overrides)
    assert report.rejected == [], report.rejected
    (candidate,) = report.accepted
    return candidate


def rejected_reason(proposal, **overrides) -> str:
    report = validate(proposal, **overrides)
    assert report.accepted == []
    (rejection,) = report.rejected
    assert rejection.candidate is proposal
    return rejection.reason


def validated(start: float, end: float, **overrides) -> ValidatedCandidate:
    fields = {
        "start": start,
        "end": end,
        "title": f"Clip {start:.0f}",
        "hook": "hook",
        "rationale": "why",
        "category": "story",
        "transcript_excerpt": "words",
        "hook_score": 80,
        "entertainment_score": 80,
        "clarity_score": 80,
        "payoff_score": 80,
        "completeness_score": 80,
        "window_index": 0,
    }
    fields.update(overrides)
    return ValidatedCandidate(**fields)


# --- snapping (deterministic corrections) --------------------------------------------------


def test_exact_line_boundaries_pass_through():
    candidate = accepted(raw_candidate(610.0, 640.0))
    assert (candidate.start, candidate.end) == (610.0, 640.0)
    assert candidate.duration == 30.0
    assert candidate.window_index == 3
    assert candidate.transcript_excerpt == "line 2 line 3 line 4 line 5 line 6 line 7"


def test_times_inside_lines_snap_outwards_to_line_boundaries():
    candidate = accepted(raw_candidate(612.3, 638.9))
    assert (candidate.start, candidate.end) == (610.0, 640.0)


def test_excerpt_is_our_transcript_not_the_models_text():
    candidate = accepted(raw_candidate(610.0, 640.0, rationale="He said 'banana' twice"))
    assert "banana" not in candidate.transcript_excerpt
    assert candidate.transcript_excerpt.startswith("line 2")


def test_overlong_clip_is_shortened_from_the_end_to_a_line_boundary():
    candidate = accepted(raw_candidate(600.0, 695.0))  # 95 s, max 60
    assert (candidate.start, candidate.end) == (600.0, 660.0)
    assert candidate.duration == 60.0


def test_shortened_clip_that_becomes_too_short_is_rejected():
    reason = rejected_reason(raw_candidate(600.0, 700.0), max_clip_seconds=12, min_clip_seconds=15)
    assert "too short" in reason


def test_single_line_longer_than_the_maximum_is_rejected():
    window = AnalysisWindow(
        index=0, start=0.0, end=200.0, lines=(TranscriptLine(0.0, 200.0, "monologue"),)
    )
    reason = rejected_reason(raw_candidate(0.0, 200.0), window=window)
    assert "single transcript line exceeds" in reason


# --- rejections ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("proposal", "fragment"),
    [
        (raw_candidate(-5.0, 20.0), "start before 0"),
        (raw_candidate(640.0, 640.0), "end not after start"),
        (raw_candidate(650.0, 640.0), "end not after start"),
        (raw_candidate(float("nan"), 640.0), "start is not finite"),
        (raw_candidate(600.0, float("inf")), "end is not finite"),
        (raw_candidate(100.0, 140.0), "outside the analysed transcript"),  # before window
        (raw_candidate(900.0, 940.0), "outside the analysed transcript"),  # after window
        (raw_candidate(610.0, 615.0), "too short"),
        (raw_candidate(3700.0, 3740.0), "start after the end of the video"),
    ],
)
def test_bad_times_are_rejected(proposal, fragment):
    assert fragment in rejected_reason(proposal)


def test_times_that_overrun_the_video_are_rejected_after_snapping():
    window = AnalysisWindow(
        index=0,
        start=0.0,
        end=130.0,
        lines=(TranscriptLine(0.0, 20.0, "a"), TranscriptLine(100.0, 130.0, "b")),
    )
    reason = rejected_reason(
        raw_candidate(100.0, 120.0), window=window, video_duration=110.0, tolerance_seconds=1.0
    )
    assert "ends after the end of the video" in reason


@pytest.mark.parametrize(
    "overrides",
    [
        {"hook_score": 101},
        {"entertainment_score": -1},
        {"clarity_score": 70.5},
        {"payoff_score": float("nan")},
        {"completeness_score": "high"},
    ],
)
def test_bad_scores_are_rejected_not_clamped(overrides):
    reason = rejected_reason(raw_candidate(610.0, 640.0, **overrides))
    (name,) = overrides
    assert name in reason


def test_integral_float_scores_are_accepted():
    candidate = accepted(raw_candidate(610.0, 640.0, hook_score=77.0))
    assert candidate.hook_score == 77 and isinstance(candidate.hook_score, int)


@pytest.mark.parametrize("field", ["title", "hook", "rationale"])
def test_empty_text_is_rejected(field):
    assert f"empty {field}" in rejected_reason(raw_candidate(610.0, 640.0, **{field: "  \u0000 "}))


# --- text and category corrections ----------------------------------------------------------


def test_text_is_normalised_and_truncated_on_a_word_boundary():
    candidate = accepted(
        raw_candidate(
            610.0,
            640.0,
            title="  Big\u0000  reveal ",
            hook="word " * 100,  # 500 chars, limit 300
            rationale="x" * 1500,
        )
    )
    assert candidate.title == "Big reveal"
    assert len(candidate.hook) <= 300 and candidate.hook.endswith("…")
    assert not candidate.hook.endswith(" …")
    assert len(candidate.rationale) == 1000 and candidate.rationale.endswith("…")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("story", "story"),
        (" Humor ", "humor"),
        ("HOT_TAKE", "hot_take"),
        ("vibes", "other"),
        ("", "other"),
    ],
)
def test_category_is_normalised_or_falls_back_to_other(given, expected):
    assert accepted(raw_candidate(610.0, 640.0, category=given)).category == expected


def test_report_keeps_accepted_and_rejected_in_input_order():
    report = validate(
        raw_candidate(610.0, 640.0), raw_candidate(650.0, 640.0), raw_candidate(660.0, 700.0)
    )
    assert [c.start for c in report.accepted] == [610.0, 660.0]
    assert [r.candidate.start for r in report.rejected] == [650.0]


def test_empty_window_rejects_everything():
    window = AnalysisWindow(index=0, start=0.0, end=0.0, lines=())
    assert "no transcript" in rejected_reason(raw_candidate(0.0, 30.0), window=window)


# --- scoring ------------------------------------------------------------------------------


def test_weights_sum_to_one_and_cover_every_dimension():
    assert round(sum(WEIGHTS.values()), 9) == 1.0
    assert set(WEIGHTS) == {
        "hook_score",
        "entertainment_score",
        "clarity_score",
        "payoff_score",
        "completeness_score",
    }


def test_overall_is_a_weighted_average_on_the_same_scale():
    uniform = validated(0.0, 30.0)
    assert overall_score(uniform) == 80
    assert overall_score(validated(0.0, 30.0, **dict.fromkeys(WEIGHTS, 0))) == 0
    assert overall_score(validated(0.0, 30.0, **dict.fromkeys(WEIGHTS, 100))) == 100
    skewed = validated(
        0.0,
        30.0,
        hook_score=100,
        entertainment_score=100,
        clarity_score=0,
        payoff_score=0,
        completeness_score=0,
    )
    assert overall_score(skewed) == 55  # 0.30 + 0.25


# --- deduplication and ranking ------------------------------------------------------------------


def test_overlap_ratio_is_intersection_over_union():
    assert overlap_ratio(validated(0.0, 10.0), validated(0.0, 10.0)) == 1.0
    assert overlap_ratio(validated(0.0, 10.0), validated(20.0, 30.0)) == 0.0
    assert overlap_ratio(validated(0.0, 10.0), validated(5.0, 15.0)) == pytest.approx(1 / 3)


def test_ranking_orders_by_score_then_start_then_duration_then_title():
    items = [
        validated(300.0, 330.0, hook_score=50),  # lower score
        validated(200.0, 240.0, title="b"),  # same score, same start, longer
        validated(200.0, 230.0, title="z"),
        validated(200.0, 230.0, title="a"),  # same everything but title
        validated(100.0, 130.0),  # earliest among the top scores
    ]
    ranked = rank_candidates(items, overlap_threshold=0.5, limit=10)
    assert [(r.rank, r.candidate.start, r.candidate.title) for r in ranked] == [
        (1, 100.0, "Clip 100"),
        (2, 200.0, "a"),
        (3, 300.0, "Clip 300"),
    ]
    # "z" and "b" overlap the kept 200–230 clip by more than 50 % → deduplicated.


def test_duplicates_keep_the_better_scored_candidate():
    weak = validated(100.0, 140.0, hook_score=10, title="weak")
    strong = validated(102.0, 142.0, title="strong")
    ranked = rank_candidates([weak, strong], overlap_threshold=0.5, limit=10)
    assert [r.candidate.title for r in ranked] == ["strong"]


def test_partial_overlap_below_threshold_is_kept():
    a = validated(100.0, 160.0)
    b = validated(150.0, 210.0)  # IoU 10/110 ≈ 0.09
    ranked = rank_candidates([a, b], overlap_threshold=0.5, limit=10)
    assert len(ranked) == 2


def test_limit_and_contiguous_ranks():
    # Distinct overall scores (every dimension = 5·i) so no rounding ties are involved.
    items = [
        validated(i * 100.0, i * 100.0 + 30.0, **dict.fromkeys(WEIGHTS, 5 * i)) for i in range(20)
    ]
    ranked = rank_candidates(items, overlap_threshold=0.5, limit=5)
    assert [r.rank for r in ranked] == [1, 2, 3, 4, 5]
    assert [r.overall_score for r in ranked] == [95, 90, 85, 80, 75]
    assert all(r.overall_score == overall_score(r.candidate) for r in ranked)


def test_ranking_is_deterministic_regardless_of_input_order():
    items = [validated(i * 50.0, i * 50.0 + 30.0, hook_score=(i * 37) % 100) for i in range(30)]
    forward = rank_candidates(items, overlap_threshold=0.5, limit=10)
    backward = rank_candidates(list(reversed(items)), overlap_threshold=0.5, limit=10)
    assert forward == backward


def test_no_candidates_no_ranking():
    assert rank_candidates([], overlap_threshold=0.5, limit=10) == ()
