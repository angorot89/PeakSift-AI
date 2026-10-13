"""Captions from the persisted transcript: clip-local timing, cue segmentation, safe ASS text.

Source of truth: ``TranscriptSegment`` rows (absolute seconds in the source video). Nothing
is regenerated, rewritten or "improved" — words appear exactly as transcribed, in order.

Timing (honest about precision): V0.3 stores segment-level timestamps, not word timings.
Long segments are split into short readable cues, and each word is given a share of its
segment's duration proportional to its length. That is a deterministic *approximation* of
when a word was spoken; cue boundaries inside a segment are therefore approximate, while
segment boundaries are exactly the transcript's. No karaoke/word-level sync is claimed.

Clip-local time: ``local = absolute - clip.start``. Words falling outside the clip are
dropped; cues are clamped to ``[0, clip duration]``; nothing can be negative or run past
the end of the clip.
"""

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

# Readable short-form cues: a few words, one or two short lines on a 1080-wide frame.
DEFAULT_MAX_WORDS = 7
DEFAULT_MAX_CHARS = 32
DEFAULT_MIN_WORDS = 2
# A cue shorter than this after clamping to the clip is not shown (it would only flash).
MIN_CUE_SECONDS = 0.2

_WHITESPACE = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"[.!?…。؟]['\")\]]*$")
_CLAUSE_END = re.compile(r"[,;:،]['\")\]]*$")

WORD_JOINER = "⁠"


@dataclass(frozen=True)
class SourceSegment:
    """A transcript segment in absolute seconds from the start of the source video."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Cue:
    """One caption in clip-local seconds."""

    start: float
    end: float
    text: str


# Bidi embedding/override/isolate controls could visually reorder a caption; they are
# dropped. Joiners (ZWJ/ZWNJ, used by emoji and Arabic shaping) and the LRM/RLM marks stay.
_BIDI_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def clean_text(text: str) -> str:
    """Words exactly as transcribed: control characters become spaces, whitespace collapses.
    Unicode letters, accents, Arabic, emoji and joiners are kept."""
    out = []
    for ch in text:
        if ch in _BIDI_CONTROLS:
            continue
        category = unicodedata.category(ch)
        out.append(" " if category == "Cc" else "" if category in ("Cs", "Co", "Cn") else ch)
    return _WHITESPACE.sub(" ", "".join(out)).strip()


def _words_with_times(segment: SourceSegment) -> list[tuple[str, float, float]]:
    """Spread the segment's duration over its words proportionally to their length."""
    words = clean_text(segment.text).split(" ")
    words = [w for w in words if w]
    if not words:
        return []
    weights = [len(w) + 1 for w in words]
    total = sum(weights)
    span = segment.end - segment.start
    timed, cursor = [], segment.start
    for word, weight in zip(words, weights, strict=True):
        end = cursor + span * weight / total
        timed.append((word, cursor, end))
        cursor = end
    timed[-1] = (timed[-1][0], timed[-1][1], segment.end)  # no float drift at the boundary
    return timed


def _group(
    timed: list[tuple[str, float, float]], max_words: int, max_chars: int, min_words: int
) -> list[list[tuple[str, float, float]]]:
    """Greedy, deterministic grouping that prefers to break after punctuation."""
    groups: list[list[tuple[str, float, float]]] = []
    current: list[tuple[str, float, float]] = []
    for item in timed:
        word = item[0]
        length = sum(len(w) for w, _, _ in current) + len(current) + len(word)
        if current and (len(current) >= max_words or length > max_chars):
            groups.append(current)
            current = []
        current.append(item)
        if _SENTENCE_END.search(word) or (_CLAUSE_END.search(word) and len(current) >= min_words):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    # Avoid a lonely last word when it fits on the previous cue.
    if len(groups) >= 2 and len(groups[-1]) == 1:
        merged = groups[-2] + groups[-1]
        if sum(len(w) for w, _, _ in merged) + len(merged) - 1 <= max_chars + 8:
            groups[-2:] = [merged]
    return groups


def build_cues(
    segments: Iterable[SourceSegment],
    *,
    clip_start: float,
    clip_end: float,
    max_words: int = DEFAULT_MAX_WORDS,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_words: int = DEFAULT_MIN_WORDS,
) -> list[Cue]:
    """Cues for ``[clip_start, clip_end]`` in clip-local seconds, ordered, non-overlapping."""
    if not (math.isfinite(clip_start) and math.isfinite(clip_end)) or clip_end <= clip_start:
        raise ValueError("The clip range is invalid")
    duration = clip_end - clip_start
    cues: list[Cue] = []
    for segment in segments:
        if not (math.isfinite(segment.start) and math.isfinite(segment.end)):
            continue
        if segment.end <= clip_start or segment.start >= clip_end or segment.end <= segment.start:
            continue  # entirely outside the clip, or not a real interval
        # Keep only the words (approximately) spoken inside the clip.
        inside = [
            (w, s, e)
            for w, s, e in _words_with_times(segment)
            if (s + e) / 2 >= clip_start and (s + e) / 2 < clip_end
        ]
        for group in _group(inside, max_words, max_chars, min_words):
            start = max(group[0][1], clip_start) - clip_start
            end = min(group[-1][2], clip_end) - clip_start
            start, end = max(0.0, start), min(duration, end)
            if cues and start < cues[-1].end:
                start = cues[-1].end  # overlapping transcript segments never stack captions
            if end - start < MIN_CUE_SECONDS:
                continue
            cues.append(
                Cue(start=round(start, 3), end=round(end, 3), text=" ".join(w for w, _, _ in group))
            )
    return cues


def escape_ass_text(text: str) -> str:
    """Make transcript text inert inside an ASS ``Dialogue`` line.

    - control characters (including newlines) become spaces — a cue is one logical line
    - every backslash is followed by an invisible WORD JOINER, so ``\\N``, ``\\n``, ``\\h``
      and override tags can never form (doubling backslashes does *not* work in libass)
    - braces become ``\\{`` / ``\\}``, which libass renders as literal braces, so no
      ``{...}`` override block can open
    Verified visually against libass: escaped text renders literally, unescaped does not.
    """
    text = clean_text(text)
    text = text.replace("\\", "\\" + WORD_JOINER)
    return text.replace("{", "\\{").replace("}", "\\}")
