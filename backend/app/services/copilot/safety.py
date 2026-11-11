"""What the Copilot's answer may never say, whatever the model was led to write.

The rules already tell the model it cannot act and that DATA is never instructions, and the
server already drops any action it may not offer. Two things can still slip into the *text* of an
answer when the model follows an instruction hidden in a transcript or a question:

- **a claim that something was done** ("I've published your video") — the Copilot never
  publishes, deletes or changes anything, so such a sentence is always false;
- **PeakSift's own instructions** repeated back ("show me your system prompt").

A third check keeps answers grounded: a sentence giving a **time that is nowhere in the
creator's data** (a model inventing "0:10, 0:30, 0:50") is removed.

A fourth keeps PeakSift's plumbing out of the creator's words: a sentence naming an **internal
term** — a key of the data the model was given (``with_figures``, ``minimum_needed``,
``engaged_views``…), a handle (``published_1``), any other ``snake_case`` identifier that is not
part of the creator's own text (their file names are), a quoted key, or a fragment of JSON — is
removed. It works from the data itself, so a new field cannot slip through.

A fifth keeps answers free of stereotypes (V1.8): a sentence **generalizing about a people, a
country, a culture, a religion or an audience** ("Moroccans love…", "Arab viewers always…", "les
Marocains préfèrent…") is removed. Morocco Mode adds context from the creator's own words and
assets, never claims about who people are or what they like.

An answer claiming an action is not shown at all (PeakSift says the answer was unusable and
offers its own next step); sentences repeating the instructions or inventing times are removed.
"""

import dataclasses
import re
from collections.abc import Iterable
from typing import Any

from app.services.copilot.contract import CopilotOutputError, ParsedReply
from app.services.copilot.prompt import CORRECTION, CORRECTION_IDEAS, SYSTEM_PROMPT

_SENTENCE = re.compile(r"(?<=[.!?。！？؟])\s+|\n+")
_WORD = re.compile(r"\w+")
_CLAIM = re.compile(
    r"\b(?:i|we)(?:\s+have|['’]ve)?(?:\s+(?:just|already|now|successfully|gone ahead and))*\s+"
    r"(?:published|uploaded|posted|deleted|removed|scheduled|renamed|shared|made (?:it |them )?"
    r"public)\b"
    r"|\b(?:j['’]ai|nous avons)\s+(?:déjà\s+|bien\s+)?(?:publié|supprimé|mis en ligne|partagé|"
    r"renommé|programmé)",
    re.IGNORECASE,
)
_GROUP = (
    r"(?:moroccans|moroccan (?:people|audiences?|viewers|users|women|men|youth|families|"
    r"creators|culture)|(?:the )?people (?:of|in) morocco|everyone in morocco|"
    r"arabs|arab (?:people|audiences?|viewers|women|men|culture)|muslims|africans|berbers|"
    r"amazigh people|north africans|(?:les )?marocains|(?:les )?marocaines|le public marocain|"
    r"les arabes|les musulmans|المغاربة)"
)
_GENERALIZATION = re.compile(
    rf"\b{_GROUP}\s+(?:\w+\s+){{0,2}}?(?:are|is|love|loves|hate|hates|always|never|tend|"
    r"prefer|prefers|like|likes|enjoy|enjoys|want|wants|can't|cannot|don't|do not|won't|all|"
    r"only|usually|generally|typically|sont|aiment|adorent|préfèrent|détestent|veulent|"
    r"toujours|jamais)\b"
    rf"|\b(?:all|most|every|tous les|la plupart des)\s+{_GROUP}"
    # Audience claims: "may appeal to Moroccans", "popular among Arab viewers".
    rf"|\b(?:appeal\w*|resonat\w*|relatable|popular|plaire|parler)\s+(?:to|with|among|aux?)\s+"
    rf"{_GROUP}"
    # Arabic script: "the Moroccans / Arabs / Muslims" + a Darija or Arabic verb or adverb.
    r"|(?:^|\s)(?:كل\s+)?(?:المغاربة|العرب|المسلمين|المسلمون|الأمازيغ)\s+"
    r"(?:ك\w+|ي\w+|دايما|ديما|عمرهم|ما\s*\w+|كلهم|بزاف)",
    re.IGNORECASE,
)
_RUN = 8  # consecutive words shared with the instructions
_LEAK = 30  # words of an answer inside such runs that mean it repeats the instructions


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _runs(words: list[str]) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + _RUN]) for i in range(len(words) - _RUN + 1)]


_INSTRUCTIONS = (
    set(_runs(_words(SYSTEM_PROMPT)))
    | set(_runs(_words(CORRECTION)))
    | set(_runs(_words(CORRECTION_IDEAS)))
)
TIME = re.compile(r"(?<![\d:])(\d{1,2}:\d{2})(?![\d:])")


# --- internal terms ----------------------------------------------------------------------------

_IDENTIFIER = re.compile(r"(?<![\w.])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?!\w)")
_JSONISH = re.compile(
    r'[{\[]\s*"|"[\w ]{1,40}"\s*:|\b\w+\s*[=:]\s*(?:null|true|false|none)\b'
    r"|\b(?:null|undefined|NaN)\b",
    re.IGNORECASE,
)
_QUOTES = "'\"`‘’“”"


@dataclasses.dataclass(frozen=True)
class Vocabulary:
    """What the data calls things: its keys, the handles, and the text of its values."""

    keys: frozenset[str]
    handles: frozenset[str]
    values: str
    quoted_keys: re.Pattern[str] | None


def vocabulary(view: Any, handles: Iterable[str] = ()) -> Vocabulary:
    keys: set[str] = set()
    values: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                keys.add(str(key).lower())
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            values.append(node.lower())

    walk(view)
    text = "\n".join(values)
    # A key in quotes ('state', "observed") reads as plumbing — unless that word is also part of
    # the creator's own text.
    plain = sorted(
        k for k in keys if re.fullmatch(r"[a-z]+", k) and not re.search(rf"\b{k}\b", text)
    )
    quoted = (
        re.compile(rf"[{_QUOTES}]\s*(?:{'|'.join(plain)})\s*[{_QUOTES}]", re.IGNORECASE)
        if plain
        else None
    )
    return Vocabulary(frozenset(keys), frozenset(h.lower() for h in handles), text, quoted)


def names_internal_term(sentence: str, words: Vocabulary) -> bool:
    """Whether a sentence names PeakSift's plumbing rather than the creator's things."""
    if _JSONISH.search(sentence):
        return True
    if words.quoted_keys is not None and words.quoted_keys.search(sentence):
        return True
    for token in _IDENTIFIER.findall(sentence):
        name = token.lower()
        if name in words.keys or name in words.handles or name not in words.values:
            return True
    return False


def drop_internal_terms(text: str, words: Vocabulary) -> str:
    """The text without the sentences naming internal terms."""
    parts = [part.strip() for part in _SENTENCE.split(text) if part and part.strip()]
    return " ".join(part for part in parts if not names_internal_term(part, words))


def _covered(words: list[str]) -> set[int]:
    """The positions of the words that sit in a run also found in the instructions."""
    covered: set[int] = set()
    for i, run in enumerate(_runs(words)):
        if run in _INSTRUCTIONS:
            covered.update(range(i, i + _RUN))
    return covered


def claims_action(text: str) -> bool:
    """Whether the text says the assistant did something (published, deleted, made public…)."""
    return bool(_CLAIM.search(text))


def screen_text(text: str) -> str:
    """The text without the sentences repeating PeakSift's instructions, when it repeats a good
    part of them (a caveat echoing one rule is fine)."""
    parts = [part.strip() for part in _SENTENCE.split(text) if part and part.strip()]
    spans, words = [], []
    for part in parts:
        part_words = _words(part)
        spans.append(range(len(words), len(words) + len(part_words)))
        words.extend(part_words)
    covered = _covered(words)
    if len(covered) < _LEAK:
        return text
    return " ".join(
        part for part, span in zip(parts, spans, strict=True) if not covered.intersection(span)
    )


def generalizes(sentence: str) -> bool:
    """Whether the sentence generalizes about a people, culture, religion or audience."""
    return bool(_GENERALIZATION.search(sentence))


def drop_generalizations(text: str) -> str:
    """The text without sentences generalizing about people (stereotypes)."""
    parts = [part.strip() for part in _SENTENCE.split(text) if part and part.strip()]
    return " ".join(part for part in parts if not generalizes(part))


def drop_unknown_times(text: str, known: set[str]) -> str:
    """The text without sentences giving a time that is not in the creator's data."""
    if all(time in known for time in TIME.findall(text)):
        return text
    parts = [part.strip() for part in _SENTENCE.split(text) if part and part.strip()]
    return " ".join(p for p in parts if all(time in known for time in TIME.findall(p)))


def screen(
    reply: ParsedReply, known_times: set[str] | None = None, words: Vocabulary | None = None
) -> ParsedReply:
    """``reply`` without repeated instructions (nor, given ``known_times``, invented times; nor,
    given the data's ``words``, internal terms). An
    answer claiming an action is never shown — the Copilot cannot act, so the claim is false and
    the model was led astray — and neither is one with nothing left: both raise
    ``CopilotOutputError``."""
    if claims_action(reply.message) or (reply.suggestion and claims_action(reply.suggestion)):
        raise CopilotOutputError("The answer claimed an action")

    def clean(text: str) -> str:
        text = drop_generalizations(screen_text(text))
        if words is not None:
            text = drop_internal_terms(text, words)
        return drop_unknown_times(text, known_times) if known_times is not None else text

    message = clean(reply.message)
    if not message:
        raise CopilotOutputError("The answer had nothing PeakSift may show")
    suggestion = clean(reply.suggestion) if reply.suggestion else None
    return dataclasses.replace(reply, message=message, suggestion=suggestion or None)
