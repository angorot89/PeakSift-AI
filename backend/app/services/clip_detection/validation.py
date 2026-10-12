"""Stage C: decide which raw model proposals may become records.

Policy (documented so behaviour is predictable):

Deterministic corrections — applied silently because they do not change *what* the model
picked, only make it precise:
- start/end are snapped to transcript line boundaries inside the analysis window
  (a clip starts where a line starts and ends where a line ends)
- a clip longer than the maximum is shortened from the end to the last line boundary
  that fits
- title/hook/rationale are normalised and truncated to their column limits
- an unknown category becomes ``other``

Rejections — the proposal is dropped (and counted) because trusting it would store
something false:
- non-finite, negative or inverted times; a range that touches no transcript line of
  the window; a range outside the video
- shorter than the minimum after snapping (or after shortening)
- any score outside 0–100, non-finite, or not a whole number
- empty title, hook or rationale

No value is ever clamped or invented: a score of 140 means the model is confused, and a
confused proposal is not a good clip.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.models.clip_detection import (
    CANDIDATE_CATEGORIES,
    HOOK_MAX_LENGTH,
    RATIONALE_MAX_LENGTH,
    SCORE_MAX,
    SCORE_MIN,
    TITLE_MAX_LENGTH,
)
from app.services.clip_detection.contract import AnalysisWindow, RawCandidate, TranscriptLine
from app.services.clip_detection.windowing import excerpt, normalize_text

SCORE_FIELDS = (
    "hook_score",
    "entertainment_score",
    "clarity_score",
    "payoff_score",
    "completeness_score",
)


@dataclass(frozen=True)
class ValidatedCandidate:
    """A proposal that survived validation, with snapped times and our transcript excerpt."""

    start: float
    end: float
    title: str
    hook: str
    rationale: str
    category: str
    transcript_excerpt: str
    hook_score: int
    entertainment_score: int
    clarity_score: int
    payoff_score: int
    completeness_score: int
    window_index: int

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Rejection:
    candidate: RawCandidate
    reason: str


@dataclass
class ValidationReport:
    accepted: list[ValidatedCandidate]
    rejected: list[Rejection]


def validate_candidates(
    proposals: Iterable[RawCandidate],
    *,
    window: AnalysisWindow,
    video_duration: float,
    min_clip_seconds: float,
    max_clip_seconds: float,
    tolerance_seconds: float,
) -> ValidationReport:
    report = ValidationReport(accepted=[], rejected=[])
    for proposal in proposals:
        try:
            report.accepted.append(
                _validate_one(
                    proposal,
                    window=window,
                    video_duration=video_duration,
                    min_clip_seconds=min_clip_seconds,
                    max_clip_seconds=max_clip_seconds,
                    tolerance_seconds=tolerance_seconds,
                )
            )
        except _Reject as rejection:
            report.rejected.append(Rejection(candidate=proposal, reason=str(rejection)))
    return report


class _Reject(Exception):
    pass


def _validate_one(
    proposal: RawCandidate,
    *,
    window: AnalysisWindow,
    video_duration: float,
    min_clip_seconds: float,
    max_clip_seconds: float,
    tolerance_seconds: float,
) -> ValidatedCandidate:
    start, end = _finite(proposal.start, "start"), _finite(proposal.end, "end")
    if start < 0:
        raise _Reject("start before 0")
    if end <= start:
        raise _Reject("end not after start")
    if video_duration > 0 and start >= video_duration + tolerance_seconds:
        raise _Reject("start after the end of the video")

    start_line, end_line = _snap(window.lines, start, end, tolerance_seconds)
    end_line = _shorten_to_fit(window.lines, start_line, end_line, max_clip_seconds)
    snapped_start, snapped_end = window.lines[start_line].start, window.lines[end_line].end
    duration = snapped_end - snapped_start
    if duration < min_clip_seconds:
        raise _Reject(f"too short after snapping ({duration:.1f}s)")
    if video_duration > 0 and snapped_end > video_duration + tolerance_seconds:
        raise _Reject("ends after the end of the video")

    scores = {name: _score(getattr(proposal, name), name) for name in SCORE_FIELDS}
    title = _text(proposal.title, TITLE_MAX_LENGTH, "title")
    hook = _text(proposal.hook, HOOK_MAX_LENGTH, "hook")
    rationale = _text(proposal.rationale, RATIONALE_MAX_LENGTH, "rationale")
    category = str(proposal.category or "").strip().lower()
    if category not in CANDIDATE_CATEGORIES:
        category = "other"

    return ValidatedCandidate(
        start=snapped_start,
        end=snapped_end,
        title=title,
        hook=hook,
        rationale=rationale,
        category=category,
        transcript_excerpt=excerpt(window.lines, snapped_start, snapped_end),
        window_index=window.index,
        **scores,
    )


# --- pieces ------------------------------------------------------------------------------------


def _finite(value: object, name: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise _Reject(f"{name} is not a number") from error
    if not math.isfinite(number):
        raise _Reject(f"{name} is not finite")
    return number


def _snap(
    lines: Sequence[TranscriptLine], start: float, end: float, tolerance: float
) -> tuple[int, int]:
    """Indices of the first line still playing at ``start`` and the last line that began
    before ``end``; the proposal must touch the window's transcript."""
    if not lines:
        raise _Reject("window has no transcript")
    if end < lines[0].start - tolerance or start > lines[-1].end + tolerance:
        raise _Reject("outside the analysed transcript")
    start_index = next((i for i, line in enumerate(lines) if line.end > start), None)
    end_index = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].start < end), None)
    if start_index is None or end_index is None or end_index < start_index:
        raise _Reject("touches no transcript line")
    return start_index, end_index


def _shorten_to_fit(
    lines: Sequence[TranscriptLine], start_index: int, end_index: int, max_seconds: float
) -> int:
    """Pull the end back to the latest line boundary that keeps the clip within the maximum."""
    start = lines[start_index].start
    index = end_index
    while index > start_index and lines[index].end - start > max_seconds:
        index -= 1
    if lines[index].end - start > max_seconds:
        raise _Reject("a single transcript line exceeds the maximum clip length")
    return index


def _score(value: object, name: str) -> int:
    number = _finite(value, name)
    if number != int(number):
        raise _Reject(f"{name} is not a whole number")
    score = int(number)
    if score < SCORE_MIN or score > SCORE_MAX:
        raise _Reject(f"{name} outside {SCORE_MIN}-{SCORE_MAX}")
    return score


def _text(value: object, limit: int, name: str) -> str:
    text = normalize_text(str(value or ""))
    if not text:
        raise _Reject(f"empty {name}")
    if len(text) > limit:
        cut = text[: limit - 1].rsplit(" ", 1)[0] if " " in text[: limit - 1] else text[: limit - 1]
        text = cut.rstrip() + "…"
    return text
