"""Find Clips: describe a moment in plain language, get the places it was actually said.

Everything returned is the creator's own transcript — real lines with real timestamps. Nothing
is generated and nothing is predicted: a result exists only because words of the request (or
words closely related to it, see ``find_clips_model.py``) were heard in that span, and the
result says which. That makes this a search, not a judgement; the editorial ranking of moments
stays with clip detection.

How it works, in order:

1. The request is reduced to its *spoken* words: folded (case, accents, Arabic letter forms),
   lightly stemmed, without function words and without the words of asking ("the part where I
   talk about …").
2. Every transcript line is scored for those words (BM25-style: a rare word counts more).
3. The best lines become spans: nearby hits are pulled together, then context is added (what
   follows first, then the set-up) until the span is long enough to be a clip — never longer
   than a clip may be.
4. Spans are ranked by how much of the request they cover.

Pure and deterministic: same transcript, same request, same answer.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

QUERY_MAX_CHARS = 200
MAX_TERMS = 12
MAX_RELATED = 10
DEFAULT_LIMIT = 8
RELATED_WEIGHT = 0.5  # a related word is weaker evidence than the creator's own word
NEARBY_LINES = 2  # hits this close belong to the same moment

_WORD = re.compile(r"[^\W_]+")
_LATIN = re.compile(r"^[a-z]+$")
_ARABIC_FORMS = str.maketrans(
    {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ـ": None}
)

# Function words (English and French) and the words of asking. None of them say what the
# moment is about, so none of them is searched for.
_STOPWORDS = frozenset(
    """
    a an the and or but so if then than that this these those there here it its i me my mine we
    our you your he she they them his her their is am are was were be been being do does did
    done have has had having will would can could should may might must not no yes to of in on
    at by for from with without into onto over under up down out off as about just very really
    too also all any some one two what which who whom whose how why when where while
    during after before between through around against again once ever never always
    le la les un une des du de d l et ou mais donc si que qui quoi dont ce cet cette ces je j tu
    il elle on nous vous ils elles mon ma mes ton ta tes son sa ses notre nos votre vos leur
    leurs est sont suis es etre ete ai as avons avez ont avoir fait faire pas ne n plus tres
    dans sur sous avec sans pour par en au aux y a ou quand comment pourquoi
    part parts moment moments clip clips bit section scene segment place spot time
    talk talks talking talked say says said saying tell tells told telling speak speaks spoke
    mention mentions mentioned explain explains explained discuss discusses discussed
    find show give want looking look need get
    partie passage endroit parle parles parlons parlez parlent dis dit dire explique expliquer
    """.split()
)


@dataclass(frozen=True)
class Line:
    """One transcript line (absolute seconds)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Found:
    """A span of the transcript where the request was heard."""

    start: float
    end: float
    lines: tuple[Line, ...]
    matched: tuple[str, ...]  # the creator's own words that were heard here
    related: tuple[str, ...]  # related words that were heard here
    score: int  # 0–100: the share of the request heard in this span

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def excerpt(self) -> str:
        return " ".join(line.text.strip() for line in self.lines if line.text.strip())


@dataclass(frozen=True)
class Understood:
    """What was searched for, in the creator's own spelling (the first form of each word)."""

    terms: tuple[str, ...]
    related: tuple[str, ...]


def fold(word: str) -> str:
    """Case, accents and Arabic letter forms removed, so one word has one spelling."""
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return bare.translate(_ARABIC_FORMS)


def stem(word: str) -> str:
    """A light stem for Latin-script words: ``pricing`` and ``price`` meet at ``pric``.

    Deliberately small. Over-stemming only widens the search a little; the creator still sees
    the real line. Other scripts are left as folded.
    """
    if len(word) <= 3 or not _LATIN.match(word):
        return word
    for suffix, minimum in (("iest", 3), ("ies", 2), ("ing", 3), ("est", 3), ("ed", 3), ("ly", 3)):
        if word.endswith(suffix) and len(word) - len(suffix) >= minimum:
            word = word[: -len(suffix)]
            if suffix in ("iest", "ies"):
                word += "i"
            break
    else:
        if word.endswith("es") and len(word) > 4 and not word.endswith("ses"):
            word = word[:-1]
        if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            word = word[:-1]
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    if len(word) > 3 and word.endswith("y"):
        word = word[:-1] + "i"
    return word


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def key(word: str) -> str:
    """The form two spellings of one word share."""
    return stem(fold(word))


def spoken_terms(text: str, *, limit: int = MAX_TERMS) -> dict[str, str]:
    """The request's content words: {search key: the word as typed}, in order, without
    function words and words of asking."""
    terms: dict[str, str] = {}
    for word in words(text[:QUERY_MAX_CHARS]):
        folded = fold(word)
        if folded in _STOPWORDS or len(folded) < 2:
            continue
        terms.setdefault(stem(folded), word.casefold())
        if len(terms) >= limit:
            break
    return terms


def related_terms(candidates: Iterable[str], own: dict[str, str]) -> dict[str, str]:
    """Related words (from the model) made safe to search with: single words, not already
    asked for, not function words, at most ``MAX_RELATED``."""
    related: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        parts = words(candidate[:40])
        if len(parts) != 1:
            continue
        folded = fold(parts[0])
        stemmed = stem(folded)
        if folded in _STOPWORDS or len(folded) < 2 or stemmed in own:
            continue
        related.setdefault(stemmed, parts[0].casefold())
        if len(related) >= MAX_RELATED:
            break
    return related


def search(
    lines: Sequence[Line],
    query: str,
    *,
    related: Iterable[str] = (),
    min_seconds: float,
    max_seconds: float,
    limit: int = DEFAULT_LIMIT,
) -> tuple[Understood, list[Found]]:
    """Spans of ``lines`` where ``query`` was heard, best first."""
    own = spoken_terms(query)
    extra = related_terms(related, own)
    understood = Understood(tuple(own.values()), tuple(extra.values()))
    if not own or not lines:
        return understood, []

    weights = {**dict.fromkeys(extra, RELATED_WEIGHT), **dict.fromkeys(own, 1.0)}
    line_keys = [Counter(key(word) for word in words(line.text)) for line in lines]
    count = len(lines)
    frequency = Counter(term for keys in line_keys for term in keys if term in weights)
    rarity = {
        term: math.log(1 + (count - frequency[term] + 0.5) / (frequency[term] + 0.5))
        for term in frequency
    }

    def line_score(index: int) -> float:
        keys = line_keys[index]
        return sum(
            weights[term] * rarity[term] * keys[term] / (keys[term] + 1.2)
            for term in keys
            if term in rarity
        )

    scores = [line_score(index) for index in range(count)]
    seeds = sorted((i for i in range(count) if scores[i] > 0), key=lambda i: (-scores[i], i))
    taken = [False] * count
    found: list[tuple[int, float, Found]] = []

    def seconds(lo: int, hi: int) -> float:
        return lines[hi].end - lines[lo].start

    def free(index: int) -> bool:
        return 0 <= index < count and not taken[index]

    for seed in seeds:
        if taken[seed]:
            continue
        lo = hi = seed
        if seconds(lo, hi) > max_seconds:
            continue
        # Pull in hits that sit next to this one: they are the same moment.
        grew = True
        while grew:
            grew = False
            for step in range(1, NEARBY_LINES + 1):
                after, before = hi + step, lo - step
                if (
                    free(after)
                    and scores[after] > 0
                    and all(free(i) for i in range(hi + 1, after))
                    and seconds(lo, after) <= max_seconds
                ):
                    hi, grew = after, True
                    break
                if (
                    free(before)
                    and scores[before] > 0
                    and all(free(i) for i in range(before + 1, lo))
                    and seconds(before, hi) <= max_seconds
                ):
                    lo, grew = before, True
                    break
        # Add context until it is long enough to be a clip. What follows comes first — naming a
        # topic usually opens it — then the set-up before, in turn.
        prefer_before = False
        while seconds(lo, hi) < min_seconds:
            can_before = free(lo - 1) and seconds(lo - 1, hi) <= max_seconds
            can_after = free(hi + 1) and seconds(lo, hi + 1) <= max_seconds
            if can_before and (prefer_before or not can_after):
                lo -= 1
            elif can_after:
                hi += 1
            else:
                break
            prefer_before = not prefer_before
        if seconds(lo, hi) < min_seconds:
            continue  # the recording has no room for a clip around this line

        heard = set().union(*(line_keys[i].keys() for i in range(lo, hi + 1))) & weights.keys()
        # The share of the creator's own words heard here. A related word can stand in for
        # what is missing, but only for half of it: it is weaker evidence.
        own_share = sum(1 for term in own if term in heard) / len(own)
        stand_in = RELATED_WEIGHT * (1 - own_share) if heard & extra.keys() else 0.0
        result = Found(
            start=lines[lo].start,
            end=lines[hi].end,
            lines=tuple(lines[lo : hi + 1]),
            matched=tuple(word for term, word in own.items() if term in heard),
            related=tuple(word for term, word in extra.items() if term in heard),
            score=round(100 * (own_share + stand_in)),
        )
        for index in range(lo, hi + 1):
            taken[index] = True
        found.append((result.score, sum(scores[lo : hi + 1]), result))

    found.sort(key=lambda item: (-item[0], -item[1], item[2].start))
    return understood, [result for _, _, result in found[:limit]]
