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
from typing import NamedTuple

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
# libass wraps only at spaces, so one unspaced token (a URL, CJK text) can never wrap and
# would run off a 1080-wide frame. Tokens wider than this are split into pieces; East Asian
# wide characters count double. 18 units fit one line of the largest preset (Bold, 80 px).
MAX_TOKEN_WIDTH = 18


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


# Emoji have no glyphs in the caption fonts (libass cannot draw colour emoji) and would burn
# in as empty boxes, so they are left out of captions: pictographs, dingbats, regional
# indicators, keycap and presentation selectors, tag characters.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0xE0020, 0xE007F),
)
_EMOJI_SINGLES = frozenset("\ufe0f\u20e3")


def _is_emoji(ch: str) -> bool:
    code = ord(ch)
    return ch in _EMOJI_SINGLES or any(lo <= code <= hi for lo, hi in _EMOJI_RANGES)


# Bidi embedding/override/isolate controls could visually reorder a caption; they are
# dropped. Joiners (ZWJ/ZWNJ, used by emoji and Arabic shaping) and the LRM/RLM marks stay.
_BIDI_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def clean_text(text: str, *, keep_emoji: bool = False) -> str:
    """Words exactly as transcribed: control characters become spaces, whitespace collapses.
    Unicode letters, accents, Arabic and joiners are kept; emoji are dropped (no glyphs in the
    V0.6 renderer) unless ``keep_emoji`` (the dynamic renderer has its own emoji policy)."""
    out = []
    for ch in text:
        if ch in _BIDI_CONTROLS or (_is_emoji(ch) and not keep_emoji):
            continue
        category = unicodedata.category(ch)
        out.append(" " if category == "Cc" else "" if category in ("Cs", "Co", "Cn") else ch)
    return _WHITESPACE.sub(" ", "".join(out)).strip()


def _width(ch: str) -> int:
    if unicodedata.category(ch)[0] in ("M", "C"):
        return 0  # combining marks and joiners take no space of their own
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _visible(word: str) -> bool:
    """False for a token made only of joiners/marks (e.g. what is left of an emoji)."""
    return any(unicodedata.category(ch)[0] not in ("C", "M") for ch in word)


def split_long_token(word: str, max_width: int = MAX_TOKEN_WIDTH) -> list[str]:
    """Split a token that cannot fit on one caption line into balanced pieces that can (no
    tiny tail piece that would flash by). Pieces never start with a combining mark or joiner,
    so accents and shaped letters stay attached to their base character."""
    total = sum(_width(ch) for ch in word)
    if total <= max_width:
        return [word]
    count = math.ceil(total / max_width)
    pieces, current, width, consumed = [], "", 0, 0
    for ch in word:
        w = _width(ch)
        attached = unicodedata.category(ch)[0] == "M" or ch in "\u200c\u200d"
        boundary = total * (len(pieces) + 1) / count
        if current and not attached and (width + w > max_width or consumed + w > boundary):
            pieces.append(current)
            current, width = "", 0
        current += ch
        width += w
        consumed += w
    if current:
        pieces.append(current)
    return pieces


class _Word(NamedTuple):
    text: str
    start: float
    end: float
    continues: bool = False  # a later piece of a split token (no space before it)


def _words_with_times(segment: SourceSegment, *, keep_emoji: bool = False) -> list[_Word]:
    """Spread the segment's duration over its words proportionally to their length."""
    pieces: list[tuple[str, bool]] = []
    for word in clean_text(segment.text, keep_emoji=keep_emoji).split(" "):
        if word and _visible(word):
            parts = split_long_token(word)
            pieces += [(part, index > 0) for index, part in enumerate(parts)]
    if not pieces:
        return []
    weights = [len(text) + 1 for text, _ in pieces]
    total = sum(weights)
    span = segment.end - segment.start
    timed, cursor = [], segment.start
    for (text, continues), weight in zip(pieces, weights, strict=True):
        end = cursor + span * weight / total
        timed.append(_Word(text, cursor, end, continues))
        cursor = end
    timed[-1] = timed[-1]._replace(end=segment.end)  # no float drift at the boundary
    return timed


def _group(timed: list[_Word], max_words: int, max_chars: int, min_words: int) -> list[list[_Word]]:
    """Greedy, deterministic grouping that prefers to break after punctuation. A piece of a
    split token always starts its own cue, so pieces are never re-joined with a space."""
    groups: list[list[_Word]] = []
    current: list[_Word] = []
    for item in timed:
        length = sum(len(w.text) for w in current) + len(current) + len(item.text)
        if current and (item.continues or len(current) >= max_words or length > max_chars):
            groups.append(current)
            current = []
        current.append(item)
        if _SENTENCE_END.search(item.text) or (
            _CLAUSE_END.search(item.text) and len(current) >= min_words
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    # Avoid a lonely last word when it fits on the previous cue.
    if len(groups) >= 2 and len(groups[-1]) == 1 and not groups[-1][0].continues:
        merged = groups[-2] + groups[-1]
        if sum(len(w.text) for w in merged) + len(merged) - 1 <= max_chars + 8:
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
    keep_emoji: bool = False,
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
            w
            for w in _words_with_times(segment, keep_emoji=keep_emoji)
            if clip_start <= (w.start + w.end) / 2 < clip_end
        ]
        for group in _group(inside, max_words, max_chars, min_words):
            start = max(group[0].start, clip_start) - clip_start
            end = min(group[-1].end, clip_end) - clip_start
            start, end = max(0.0, start), min(duration, end)
            if cues and start < cues[-1].end:
                start = cues[-1].end  # overlapping transcript segments never stack captions
            if end - start < MIN_CUE_SECONDS:
                continue
            cues.append(
                Cue(start=round(start, 3), end=round(end, 3), text=" ".join(w.text for w in group))
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
