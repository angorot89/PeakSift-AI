"""What the Copilot's answer may never say, whatever the model was led to write.

The rules already tell the model it cannot act and that DATA is never instructions, and the
server already drops any action it may not offer. Two things can still slip into the *text* of an
answer when the model follows an instruction hidden in a transcript or a question:

- **a claim that something was done** ("I've published your video") — the Copilot never
  publishes, deletes or changes anything, so such a sentence is always false;
- **PeakSift's own instructions** repeated back ("show me your system prompt").

An answer claiming an action is not shown at all (PeakSift says the answer was unusable and
offers its own next step); sentences repeating the instructions are removed.
"""

import dataclasses
import re

from app.services.copilot.contract import CopilotOutputError, ParsedReply
from app.services.copilot.prompt import CORRECTION, SYSTEM_PROMPT

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
_RUN = 8  # consecutive words shared with the instructions
_LEAK = 30  # words of an answer inside such runs that mean it repeats the instructions


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _runs(words: list[str]) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + _RUN]) for i in range(len(words) - _RUN + 1)]


_INSTRUCTIONS = set(_runs(_words(SYSTEM_PROMPT))) | set(_runs(_words(CORRECTION)))


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


def screen(reply: ParsedReply) -> ParsedReply:
    """``reply`` without repeated instructions. An answer claiming an action is never shown —
    the Copilot cannot act, so the claim is false and the model was led astray — and neither is
    one with nothing left: both raise ``CopilotOutputError``."""
    if claims_action(reply.message) or (reply.suggestion and claims_action(reply.suggestion)):
        raise CopilotOutputError("The answer claimed an action")
    message = screen_text(reply.message)
    if not message:
        raise CopilotOutputError("The answer had nothing PeakSift may show")
    suggestion = screen_text(reply.suggestion) if reply.suggestion else None
    return dataclasses.replace(reply, message=message, suggestion=suggestion or None)
