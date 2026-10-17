"""Keeping B-roll suggestions honest: a query must come from what was said.

A model can describe a visual well and still invent things — a brand nobody mentioned, a
person's name for "he", a city for "there". A validated suggestion is kept only when:

- **it is anchored**: at least one subject word of its query was actually said near its
  moment (within ``NEAR_SECONDS``), so the visual illustrates *that* line;
- **it invents no names**: in a sentence-case query ("photo of the Eiffel Tower at night"),
  every capitalized word after the first (and a first word like "NASA" or "SpaceX") must
  occur somewhere in the clip's transcript; a Title Case query
  ("Eiffel Tower Night View") cannot be read that way, so at least half of its subject words
  must come from the transcript instead;
- **it is concrete**: queries made only of abstract words ("success", "an important thing")
  are refused.

Words match on a short stem (``launch`` matches "launched", ``bitcoin`` matches
"Bitcoin's"), so ordinary inflection is not mistaken for invention. Grounding is a guard,
not proof of good taste: the creator still decides what to use.
"""

import re

from app.services.broll.contract import TranscriptLine
from app.services.broll.validation import Suggestion, query_words

NEAR_SECONDS = 2.0
STEM_LENGTH = 6
# Words that name feelings or abstractions rather than something a camera can show.
VAGUE_WORDS = frozenset(
    "success failure emotion feeling interesting important thing stuff idea concept "
    "motivation inspiration happiness sadness life moment situation problem solution people "
    "person someone something everything nothing way time reason point fact thought mindset "
    "energy vibe journey growth change value".split()
)
_TOKEN = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)


def stem(word: str) -> str:
    word = word.lower().strip("'’-")
    for suffix in ("'s", "’s"):
        if word.endswith(suffix):
            word = word[: -len(suffix)]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word[:STEM_LENGTH]


def stems(text: str) -> set[str]:
    return {stem(token) for token in _TOKEN.findall(text)}


def is_vague(query: str) -> bool:
    words = query_words(query)
    return not words or all(stem(word) in {stem(v) for v in VAGUE_WORDS} for word in words)


def _near_text(lines: tuple[TranscriptLine, ...], start: float, end: float) -> str:
    return " ".join(
        line.text
        for line in lines
        if line.start < end + NEAR_SECONDS and line.end > start - NEAR_SECONDS
    )


def invented_names(query: str, clip_stems: set[str]) -> bool:
    """Whether the query names something the clip never mentioned (see module docstring)."""
    tokens = _TOKEN.findall(query)
    alphabetic = [t for t in tokens if t[0].isalpha()]
    subject = query_words(query)
    title_case = len(alphabetic) > 1 and all(t[0].isupper() for t in alphabetic)
    if title_case:
        found = sum(1 for word in subject if stem(word) in clip_stems)
        return found * 2 < len(subject)
    names = [t for t in alphabetic[1:] if t[0].isupper()]
    # The first word is capitalized by grammar; only a visibly special one ("NASA", "SpaceX",
    # "iPhone") is a name.
    if alphabetic and any(c.isupper() for c in alphabetic[0][1:]):
        names.append(alphabetic[0])
    return any(stem(name) not in clip_stems for name in names)


def ground(
    suggestions: list[Suggestion], lines: tuple[TranscriptLine, ...]
) -> tuple[list[Suggestion], dict[str, int]]:
    """The grounded suggestions, and how many were refused for each reason."""
    clip_stems = stems(" ".join(line.text for line in lines))
    kept: list[Suggestion] = []
    rejected: dict[str, int] = {}

    def refuse(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for suggestion in suggestions:
        if is_vague(suggestion.query):
            refuse("vague")
            continue
        near = stems(_near_text(lines, suggestion.start, suggestion.end))
        if not any(stem(word) in near for word in query_words(suggestion.query)):
            refuse("not_said_here")
            continue
        if invented_names(suggestion.query, clip_stems):
            refuse("invented_name")
            continue
        kept.append(suggestion)
    return kept, rejected
