"""Checking B-roll suggestions before they are stored: timing, text, score, duplicates, density.

Everything a suggestion provider returns is untrusted. A suggestion is kept only when:

- its interval is finite, starts at or after 0, ends inside the clip and lasts between
  ``MIN_SUGGESTION_SECONDS`` and ``MAX_SUGGESTION_SECONDS`` — nothing is clamped, trimmed or
  invented to make a bad interval fit;
- its query and reason are non-empty plain text within their limits (whitespace collapsed);
- its score, when given, is a whole number on the 0–100 editorial scale.

Then equivalent suggestions ("moon", "the Moon", "Moon footage") for the same moment collapse
into one, overlapping suggestions keep the stronger one, and the result is capped to a
restrained density (about one visual per ``SECONDS_PER_SUGGESTION`` of clip) — B-roll should
break up a talking head, not cover it.
"""

import math
import re
from dataclasses import dataclass, field

from app.models.broll import QUERY_MAX_LENGTH, REASON_MAX_LENGTH, SCORE_MAX, SCORE_MIN

MIN_SUGGESTION_SECONDS = 1.0
MAX_SUGGESTION_SECONDS = 6.0
SECONDS_PER_SUGGESTION = 7.0  # density: at most one suggestion per 7 s of clip
MAX_SUGGESTIONS = 8
# Equivalent queries closer than this (seconds between intervals) are the same idea.
DUPLICATE_WINDOW_SECONDS = 2.0
TIME_DECIMALS = 2
DEFAULT_RANK_SCORE = 50  # a suggestion without a score ranks in the middle

# Words that describe the *medium* rather than the subject, ignored when comparing queries.
_FILLER = frozenset(
    "a an the of some any footage video videos clip clips image images photo photos picture "
    "pictures shot shots broll b-roll stock visual visuals graphic graphics illustration "
    "showing shows show close closeup close-up view scene".split()
)
_WORD = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(frozen=True)
class RawSuggestion:
    """Exactly what a provider proposed, in clip-local seconds. Untrusted until validated."""

    start: object
    end: object
    query: object
    reason: object
    score: object = None


@dataclass(frozen=True)
class Suggestion:
    start: float
    end: float
    query: str
    reason: str
    score: int | None

    @property
    def rank_score(self) -> int:
        return DEFAULT_RANK_SCORE if self.score is None else self.score


@dataclass
class ValidationReport:
    kept: list[Suggestion] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    @property
    def rejected_count(self) -> int:
        return sum(self.rejected.values())


def clean_text(value: object, limit: int) -> str | None:
    """Collapse whitespace and trim surrounding quotes; None when empty, not text or too long."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip(" \"'“”‘’`")
    if not text or len(text) > limit:
        return None
    return text


def query_words(query: str) -> frozenset[str]:
    """The subject words of a query: lower case, singular-ish, medium words removed."""
    words = set()
    for word in _WORD.findall(query.lower()):
        word = word.strip("'-")
        if not word or word in _FILLER:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.add(word)
    return frozenset(words)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _score(value: object) -> tuple[bool, int | None]:
    """(ok, score). Whole numbers 0-100 only; 85.0 is 85, 85.5 or "85" or True is refused."""
    if value is None:
        return True, None
    number = _number(value)
    if number is None or number != int(number) or not SCORE_MIN <= number <= SCORE_MAX:
        return False, None
    return True, int(number)


def max_suggestions(clip_duration: float) -> int:
    """The density cap: about one visual per SECONDS_PER_SUGGESTION, at least one."""
    return max(1, min(MAX_SUGGESTIONS, int(clip_duration // SECONDS_PER_SUGGESTION)))


def check_one(
    raw: RawSuggestion, clip_duration: float, report: ValidationReport
) -> Suggestion | None:
    start, end = _number(raw.start), _number(raw.end)
    if start is None or end is None:
        report.reject("invalid_time")
        return None
    if start < 0 or end > clip_duration or end <= start:
        report.reject("outside_clip")
        return None
    length = end - start
    if length < MIN_SUGGESTION_SECONDS or length > MAX_SUGGESTION_SECONDS:
        report.reject("bad_length")
        return None
    query = clean_text(raw.query, QUERY_MAX_LENGTH)
    reason = clean_text(raw.reason, REASON_MAX_LENGTH)
    if query is None or reason is None or not query_words(query):
        report.reject("invalid_text")
        return None
    ok, score = _score(raw.score)
    if not ok:
        report.reject("invalid_score")
        return None
    return Suggestion(
        start=round(start, TIME_DECIMALS),
        end=round(end, TIME_DECIMALS),
        query=query,
        reason=reason,
        score=score,
    )


def _overlap(a: Suggestion, b: Suggestion, margin: float = 0.0) -> bool:
    return a.start < b.end + margin and b.start < a.end + margin


def _equivalent(a: Suggestion, b: Suggestion) -> bool:
    wa, wb = query_words(a.query), query_words(b.query)
    return wa <= wb or wb <= wa


def select_suggestions(
    candidates: list[Suggestion], clip_duration: float, report: ValidationReport
) -> list[Suggestion]:
    """Collapse duplicates, resolve overlaps and cap density, keeping the strongest first.

    Ties keep the earlier suggestion, so the result is deterministic for a given input.
    """
    ranked = sorted(candidates, key=lambda s: (-s.rank_score, s.start, s.end, s.query))
    kept: list[Suggestion] = []
    for suggestion in ranked:
        if any(
            _equivalent(suggestion, k) and _overlap(suggestion, k, DUPLICATE_WINDOW_SECONDS)
            for k in kept
        ):
            report.reject("duplicate")
            continue
        if any(_overlap(suggestion, k) for k in kept):
            report.reject("overlap")
            continue
        kept.append(suggestion)
    cap = max_suggestions(clip_duration)
    for _ in kept[cap:]:
        report.reject("density")
    return sorted(kept[:cap], key=lambda s: (s.start, s.end))


def validate_suggestions(raw: list[RawSuggestion], clip_duration: float) -> ValidationReport:
    """Check every raw suggestion, then select the ones worth showing (see module docstring)."""
    report = ValidationReport()
    if not _number(clip_duration) or clip_duration <= 0:
        for _ in raw:
            report.reject("outside_clip")
        return report
    checked = [s for s in (check_one(item, clip_duration, report) for item in raw) if s is not None]
    report.kept = select_suggestions(checked, clip_duration, report)
    return report
