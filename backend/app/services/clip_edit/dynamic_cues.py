"""Word-aware caption cues for the dynamic (``caption_v2``) renderer.

Input: timed words in clip-local seconds — real provider word timing from a completed
``CaptionTrack`` (``aligned_word``), or phrase-timed transcript cues (``phrase_fallback``).
Output: short cues of one or two lines whose words stay individually addressable, so the
renderer and the browser preview can emphasise the word being spoken. Deterministic: no
model, no randomness; equal input gives equal cues.

**Grouping.** Words are added to the current cue until one of these closes it: a sentence
end (``. ! ? …``), a clause end (``, ; :``) once the cue has ``min_words``, a natural pause
(``pause_seconds`` between words), or a limit — ``max_words``, two lines of ``line_units``
width, ``max_duration`` seconds. A lone trailing word is merged back into the previous cue
when that still fits (no orphan cues).

**Lines.** A cue that fits ``line_units`` is one line; otherwise it is split into two lines
at the most balanced break that keeps both lines within ``line_units`` — preferring breaks
after punctuation and avoiding a single-word second line. Line breaks are decided here (not
by libass wrapping), so the preview and the render show the same lines. Widths are measured
in character units (1 per character, 2 for East Asian wide characters, 0 for combining marks
and joiners) and each preset declares how many units fit a line at its size.

**Timing.** A cue starts with its first word and ends shortly after its last word
(``hold_seconds``), never overlapping the next cue and never past the clip; very short cues
are extended up to ``min_duration`` when there is room. Within a word-timed cue each word is
*active* from its own start until the next word starts (gaps up to ``bridge_seconds`` are
bridged, so the highlight never blinks off between words) and the last word until the cue
ends. Phrase-timed cues have no per-word timing (``timed=False``): their words are never
highlighted individually. Text is never changed: words appear exactly as recognized.
"""

import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

SENTENCE_END = re.compile(r"[.!?…。؟]['\")\]»”’]*$")
CLAUSE_END = re.compile(r"[,;:،—–]['\")\]»”’]*$")


def char_units(ch: str) -> int:
    if unicodedata.category(ch)[0] in ("M", "C"):
        return 0  # combining marks, joiners and format characters take no space of their own
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def text_units(text: str) -> int:
    return sum(char_units(ch) for ch in text)


@dataclass(frozen=True)
class CueRules:
    # The width budget of one line, in the units of ``measure``: character units by default;
    # the dynamic presets measure real glyph advances in pixels (see ``caption_metrics.py``).
    line_units: float = 18
    measure: Callable[[str], float] = text_units
    space: float = 1  # the width of the space between two words, in the same units
    max_lines: int = 2
    max_words: int = 7
    min_words: int = 2  # a clause end closes a cue only once it has this many words
    max_duration: float = 3.2
    min_duration: float = 0.7
    pause_seconds: float = 0.45
    hold_seconds: float = 0.25
    bridge_seconds: float = 0.35


DEFAULT_RULES = CueRules()


@dataclass(frozen=True)
class SourceWord:
    """A word to place, in clip-local seconds."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class CueWord:
    text: str
    start: float  # active from
    end: float  # active until
    attached: bool = False  # a later piece of a split token (no space before it)


@dataclass(frozen=True)
class WordCue:
    start: float
    end: float
    words: tuple[CueWord, ...]
    lines: tuple[int, ...]  # index of the first word of each line (always starts with 0)
    timed: bool  # True: real word timing (highlight words); False: phrase timing only

    def line_words(self) -> list[tuple[CueWord, ...]]:
        bounds = [*self.lines, len(self.words)]
        return [self.words[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]

    def active_index(self, t: float) -> int | None:
        """The word being spoken at clip time ``t`` (None between cues or when untimed)."""
        if not self.timed or not (self.start <= t < self.end):
            return None
        for index, word in enumerate(self.words):
            if word.start <= t < word.end:
                return index
        return None


def split_token(
    text: str, max_units: float, measure: Callable[[str], float] = text_units
) -> list[str]:
    """Split one token wider than a line into balanced pieces, never separating a combining
    mark or joiner from the character before it (grapheme-safe for accents and emoji ZWJ)."""
    total = measure(text)
    if total <= max_units:
        return [text]
    count = math.ceil(total / max_units)
    pieces: list[str] = []
    current, width, consumed = "", 0.0, 0.0
    for ch in text:
        w = measure(ch)
        attached = w == 0 or ch == "\u200d" or (current and current[-1] == "\u200d")
        boundary = total * (len(pieces) + 1) / count
        if current and not attached and (width + w > max_units or consumed + w > boundary):
            pieces.append(current)
            current, width = "", 0
        current += ch
        width += w
        consumed += w
    if current:
        pieces.append(current)
    return pieces


def _line_width(words: Sequence[CueWord], rules: CueRules) -> float:
    width = 0.0
    for index, word in enumerate(words):
        width += rules.measure(word.text) + (rules.space if index and not word.attached else 0)
    return width


def _greedy_lines(words: Sequence[CueWord], rules: CueRules) -> tuple[int, ...]:
    """Fill lines left to right — only for a cue made of one over-long token (a URL), which
    may need more than two lines rather than losing text."""
    starts, width = [0], 0
    for index, word in enumerate(words):
        w = rules.measure(word.text) + (rules.space if index and not word.attached else 0)
        if index and width + w > rules.line_units:
            starts.append(index)
            width = rules.measure(word.text)
        else:
            width += w
    return tuple(starts)


def layout_lines(words: Sequence[CueWord], rules: CueRules) -> tuple[int, ...] | None:
    """Line starts for ``words`` within ``rules.max_lines`` lines, or None if they cannot fit."""
    if _line_width(words, rules) <= rules.line_units:
        return (0,)
    if rules.max_lines < 2:
        return None
    best: tuple[float, int] | None = None
    for cut in range(1, len(words)):
        first, second = words[:cut], words[cut:]
        a, b = _line_width(first, rules), _line_width(second, rules)
        if a > rules.line_units or b > rules.line_units:
            continue
        score = abs(a - b)
        if len(second) == 1 and len(words) > 2:
            score += rules.line_units  # a single-word second line looks broken
        if CLAUSE_END.search(first[-1].text) or SENTENCE_END.search(first[-1].text):
            score -= rules.line_units / 3  # a natural break reads better
        if second[0].attached:
            score += rules.line_units / 2  # avoid breaking a split token when possible
        if best is None or score < best[0]:
            best = (score, cut)
    return None if best is None else (0, best[1])


def _pieces(words: Iterable[SourceWord], rules: CueRules) -> list[CueWord]:
    out: list[CueWord] = []
    for word in words:
        text = " ".join(word.text.split())
        if not text:
            continue
        for index, piece in enumerate(split_token(text, rules.line_units, rules.measure)):
            # Pieces share the word's real interval: no sub-word time is invented.
            out.append(CueWord(piece, word.start, word.end, attached=index > 0))
    return out


def _fits(words: Sequence[CueWord], rules: CueRules) -> bool:
    if all(w.attached for w in words[1:]):
        return True  # one token (possibly split): it is shown whole, on as many lines as needed
    return len(words) <= rules.max_words and layout_lines(words, rules) is not None


def _group(pieces: list[CueWord], rules: CueRules) -> list[list[CueWord]]:
    groups: list[list[CueWord]] = []
    current: list[CueWord] = []

    def close() -> None:
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for piece in pieces:
        # Pieces of one split token share one real interval, so they always stay in one cue.
        if current and not piece.attached:
            pause = piece.start - current[-1].end >= rules.pause_seconds
            too_long = piece.end - current[0].start > rules.max_duration
            if pause or too_long or not _fits([*current, piece], rules):
                close()
        current.append(piece)
        # Punctuation closes a cue only once it has been on screen long enough to read; in
        # fast speech the following words join it (the width and duration limits still apply).
        readable = piece.end - current[0].start >= rules.min_duration
        if readable and (
            SENTENCE_END.search(piece.text)
            or (CLAUSE_END.search(piece.text) and len(current) >= rules.min_words)
        ):
            close()
    close()
    # A lone trailing word joins the previous cue when that still reads as one thought, or
    # takes the previous cue's last word with it when merging would not fit (no orphan cues).
    merged: list[list[CueWord]] = []
    for group in groups:
        previous = merged[-1] if merged else None
        lonely = (
            rules.max_words > 1  # one word at a time: a single word is the point, not lonely
            and previous is not None
            and len(group) == 1
            and not group[0].attached
            and not SENTENCE_END.search(previous[-1].text)
            and group[0].start - previous[-1].end < rules.pause_seconds
        )
        if (
            lonely
            and group[0].end - previous[0].start <= rules.max_duration + 0.8
            and _fits([*previous, *group], replace(rules, max_words=rules.max_words + 1))
        ):
            merged[-1] = [*previous, *group]
        elif (
            lonely
            and len(previous) >= 3
            and not previous[-1].attached
            and _fits(previous[:-1], rules)
            and _fits([previous[-1], *group], rules)
        ):
            merged[-1] = previous[:-1]
            merged.append([previous[-1], *group])
        else:
            merged.append(group)
    return merged


def build_word_cues(
    words: Iterable[SourceWord], *, clip_duration: float, rules: CueRules = DEFAULT_RULES
) -> list[WordCue]:
    """Cues from real word timing (``aligned_word``): ordered, non-overlapping, in the clip."""
    if not (math.isfinite(clip_duration) and clip_duration > 0):
        raise ValueError("The clip duration is invalid")
    ordered = sorted(
        (w for w in words if math.isfinite(w.start) and math.isfinite(w.end) and w.end > w.start),
        key=lambda w: (w.start, w.end),
    )
    inside = [w for w in ordered if w.start < clip_duration]
    groups = _group(_pieces(inside, rules), rules)
    cues: list[WordCue] = []
    for index, group in enumerate(groups):
        start = max(0.0, group[0].start)
        if cues and start < cues[-1].end:
            start = cues[-1].end
        next_start = groups[index + 1][0].start if index + 1 < len(groups) else clip_duration
        end = min(max(group[-1].end, start) + rules.hold_seconds, next_start, clip_duration)
        if end - start < rules.min_duration:
            end = min(start + rules.min_duration, next_start, clip_duration)
        if end <= start:
            continue
        active: list[CueWord] = []
        for i, piece in enumerate(group):
            following = next((p for p in group[i + 1 :] if not p.attached), None)
            if following is None:
                until = end
            elif following.start - piece.end <= rules.bridge_seconds:
                until = following.start
            else:
                until = piece.end
            begin = max(piece.start, start)
            until = min(max(until, begin), end)
            active.append(replace(piece, start=round(begin, 3), end=round(until, 3)))
        lines = layout_lines(active, rules) or _greedy_lines(active, rules)
        cues.append(WordCue(round(start, 3), round(end, 3), tuple(active), lines, timed=True))
    return cues


def phrase_cues(
    cues: Iterable[tuple[float, float, str]],
    *,
    clip_duration: float,
    rules: CueRules = DEFAULT_RULES,
) -> list[WordCue]:
    """Phrase-timed cues (``phrase_fallback``) in the same shape, without per-word timing:
    every word carries the cue's interval and nothing is highlighted individually."""
    out: list[WordCue] = []
    for start, end, text in cues:
        start, end = max(0.0, start), min(end, clip_duration)
        if end <= start:
            continue
        pieces = _pieces([SourceWord(text_part, start, end) for text_part in text.split()], rules)
        if not pieces:
            continue
        # Respect the line budget: a phrase cue that cannot fit two lines is split in halves
        # sharing its interval evenly (phrase timing stays approximate and is labelled so).
        chunks = [pieces]
        while any(layout_lines(c, rules) is None for c in chunks):
            longest = max(chunks, key=len)
            if len(longest) < 2:
                break
            i = chunks.index(longest)
            half = len(longest) // 2
            chunks[i : i + 1] = [longest[:half], longest[half:]]
        span = (end - start) / len(chunks)
        for k, chunk in enumerate(chunks):
            a, b = start + span * k, start + span * (k + 1)
            words = tuple(replace(p, start=round(a, 3), end=round(b, 3)) for p in chunk)
            out.append(
                WordCue(
                    round(a, 3), round(b, 3), words, layout_lines(words, rules) or (0,), timed=False
                )
            )
    return out
