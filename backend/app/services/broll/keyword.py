"""The deterministic fallback: suggest visuals for the names a speaker mentions.

When no language model is available (or it fails), PeakSift can still point at obvious
visual moments: the proper names in the transcript — places, organizations, products,
landmarks ("the Eiffel Tower", "NASA", "Tokyo"). Each mention becomes a short suggestion
starting just before the name is said. Without word timestamps the moment is *estimated*
from the name's position in its line (characters spoken at an even pace), so the creator
should check the timing; suggestions are always editable.

No dictionary, network or model is involved, and the same transcript always gives the same
suggestions.
"""

import re

from app.services.broll.contract import BrollRequest, BrollResult, TranscriptLine
from app.services.broll.validation import RawSuggestion

PROVIDER_NAME = "keyword"
PROVIDER_VERSION = "proper_names_v1"
LEAD_SECONDS = 0.3  # start a little before the name is said
DEFAULT_SECONDS = 3.0
MAX_WORDS = 4
REASON_EXCERPT = 90

# Capitalized words that are not names: pronouns, sentence glue, greetings, days and months
# are visual dead ends.
_NOT_NAMES = frozenset(
    "i i'm i've i'll i'd im ive the a an and but so or if when then now this that these those "
    "we you he she it they our my your his her its their there here what how why who where "
    "yes no ok okay well hey hi hello today tomorrow yesterday also just because however "
    "monday tuesday wednesday thursday friday saturday sunday january february march april "
    "may june july august september october november december let let's".split()
)
_CONNECTORS = frozenset({"of", "de", "the", "and", "&"})
_WORD = re.compile(r"[^\W\d_][\w'’.-]*|\d[\w.,%-]*", re.UNICODE)


def _is_name_word(word: str) -> bool:
    bare = word.strip(".'’").lower()
    return word[:1].isupper() and bare not in _NOT_NAMES and len(bare) > 1


def name_mentions(text: str) -> list[tuple[str, int]]:
    """(name, character offset) for each run of capitalized words, sentence starts excepted."""
    mentions: list[tuple[str, int]] = []
    words = list(_WORD.finditer(text))
    index = 0
    while index < len(words):
        match = words[index]
        sentence_start = index == 0 or text[: match.start()].rstrip()[-1:] in ".!?"
        if not _is_name_word(match.group()):
            index += 1
            continue
        run = [match]
        cursor = index + 1
        while cursor < len(words) and len(run) < MAX_WORDS:
            word = words[cursor].group()
            if _is_name_word(word):
                run.append(words[cursor])
            elif (
                word.lower() in _CONNECTORS
                and cursor + 1 < len(words)
                and _is_name_word(words[cursor + 1].group())
            ):
                run.append(words[cursor])
            else:
                break
            cursor += 1
        # A lone capitalized word opening a sentence is usually just grammar ("Rockets are…"),
        # unless it is an acronym ("NASA plans…").
        acronym = run[0].group().strip(".").isupper()
        if not (sentence_start and len(run) == 1 and not acronym):
            name = text[run[0].start() : run[-1].end()].strip(".,'’ ")
            mentions.append((name, run[0].start()))
        index = cursor
    return mentions


def _window(line: TranscriptLine, offset: int, request: BrollRequest) -> tuple[float, float]:
    length = max(1, len(line.text))
    said = line.start + (line.end - line.start) * offset / length
    span = min(max(DEFAULT_SECONDS, request.min_seconds), request.max_seconds)
    start = max(0.0, said - LEAD_SECONDS)
    end = min(request.clip_duration, start + span)
    start = max(0.0, end - span)  # near the end of the clip, slide back rather than shrink
    return round(start, 2), round(end, 2)


def _excerpt(text: str) -> str:
    return (
        text if len(text) <= REASON_EXCERPT else text[: REASON_EXCERPT - 1].rsplit(" ", 1)[0] + "…"
    )


class KeywordBrollProvider:
    name = PROVIDER_NAME
    model = PROVIDER_VERSION

    def suggest(self, request: BrollRequest) -> BrollResult:
        seen: set[str] = set()
        suggestions: list[RawSuggestion] = []
        for line in request.lines:
            for name, offset in name_mentions(line.text):
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                start, end = _window(line, offset, request)
                suggestions.append(
                    RawSuggestion(
                        start=start,
                        end=end,
                        query=name,
                        reason=f"Mentioned in “{_excerpt(line.text)}”",
                        score=60 if " " in name else 50,
                    )
                )
        return BrollResult(tuple(suggestions), PROVIDER_NAME, PROVIDER_VERSION)
