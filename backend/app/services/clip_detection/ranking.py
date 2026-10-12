"""Stages D and E: score, deduplicate and rank validated candidates.

The overall score is a fixed weighted average of the five editorial dimensions
(documented weights below), on the same 0–100 scale. It is an editorial judgement
normalised across providers, not a probability that a clip performs well.

Ordering is total and deterministic: higher overall score, then earlier start, then
shorter duration, then title. Two candidates whose time ranges overlap by more than the
configured intersection-over-union threshold are duplicates; the better-ranked one wins.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.services.clip_detection.validation import ValidatedCandidate

# Must sum to 1. Hook and entertainment dominate because they decide whether a short
# clip is watched at all; clarity, payoff and completeness decide whether it satisfies.
WEIGHTS = {
    "hook_score": 0.30,
    "entertainment_score": 0.25,
    "clarity_score": 0.15,
    "payoff_score": 0.15,
    "completeness_score": 0.15,
}


@dataclass(frozen=True)
class RankedCandidate:
    candidate: ValidatedCandidate
    overall_score: int
    rank: int


def overall_score(candidate: ValidatedCandidate) -> int:
    total = sum(weight * getattr(candidate, name) for name, weight in WEIGHTS.items())
    return max(0, min(100, round(total)))


def overlap_ratio(a: ValidatedCandidate, b: ValidatedCandidate) -> float:
    """Intersection over union of two time ranges; 0 when disjoint, 1 when identical."""
    intersection = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = max(a.end, b.end) - min(a.start, b.start)
    return intersection / union if union > 0 else 0.0


def _order_key(item: tuple[ValidatedCandidate, int]):
    candidate, score = item
    return (-score, candidate.start, candidate.duration, candidate.title)


def rank_candidates(
    candidates: Iterable[ValidatedCandidate], *, overlap_threshold: float, limit: int
) -> tuple[RankedCandidate, ...]:
    """Deduplicate overlapping proposals, order deterministically, keep the top ``limit``."""
    scored = sorted(((c, overall_score(c)) for c in candidates), key=_order_key)
    kept: list[tuple[ValidatedCandidate, int]] = []
    for candidate, score in scored:
        if any(overlap_ratio(candidate, other) > overlap_threshold for other, _ in kept):
            continue  # a better-ranked candidate already covers this moment
        kept.append((candidate, score))
        if len(kept) == limit:
            break
    return tuple(
        RankedCandidate(candidate=candidate, overall_score=score, rank=position)
        for position, (candidate, score) in enumerate(kept, start=1)
    )
