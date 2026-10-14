"""The caption-timing provider contract: request/result types, capabilities, errors and the
validation every provider's output goes through before anything is persisted.

A provider turns an audio file into *words with timestamps*. Persistence and caption
rendering depend only on these plain types — never on a provider's own classes.

Validation policy (``validate_words``), documented because it decides what "aligned" means:

- Output that cannot be trusted at all is refused (``TimingOutputError``): a non-finite
  time, a word starting before 0, words out of order, a word ending materially past the
  audio (more than the configured tolerance).
- A single word without a usable interval (shorter than ``MIN_WORD_SECONDS``, including
  ``end <= start``) or without visible text is dropped and counted in ``rejected_words``.
  Its time is never invented.
- Small irregularities are normalized with documented tolerances: a start up to
  ``START_TOLERANCE`` below 0 becomes 0; an end within the tolerance past the audio is
  clamped to the audio duration; a word overlapping the previous one shortens the previous
  word's end to this word's start (so two words are never active at once).
- Text is kept exactly as recognized apart from surrounding whitespace (no rewording, case
  changes or punctuation clean-up).
"""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

MIN_WORD_SECONDS = 0.02
START_TOLERANCE = 0.01
ORDER_TOLERANCE = 0.01
MAX_WORD_CHARS = 128

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class TimedWord:
    """One word in seconds relative to the audio the provider saw."""

    start: float
    end: float
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class TimingCapabilities:
    word_timestamps: bool
    language_detection: bool
    confidence: bool


@dataclass(frozen=True)
class CaptionTimingRequest:
    audio_path: Path
    language_hint: str | None = None


@dataclass(frozen=True)
class CaptionTimingResult:
    provider: str
    model: str
    language: str | None
    language_probability: float | None
    audio_duration: float
    words: tuple[TimedWord, ...]
    rejected_words: int


@runtime_checkable
class CaptionTimingProvider(Protocol):
    name: str
    model: str
    capabilities: TimingCapabilities

    def time_words(self, request: CaptionTimingRequest) -> CaptionTimingResult: ...


# --- errors -------------------------------------------------------------------------------


class CaptionTimingError(Exception):
    """Timing failed. ``code`` is stable; ``message`` is safe to store and show (no paths)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class TimingUnavailable(CaptionTimingError):
    """The configured provider cannot run here (not installed, model not loadable, ...)."""


class TimingOutputError(CaptionTimingError):
    def __init__(self, message: str) -> None:
        super().__init__("timing_output_invalid", message)


def require_word_timestamps(provider: CaptionTimingProvider) -> None:
    """Word-synced captions need real word timestamps; a provider without them is refused
    rather than having its output presented as aligned."""
    if not provider.capabilities.word_timestamps:
        raise TimingUnavailable(
            "provider_capability",
            f"The caption timing provider '{provider.name}' does not return word timestamps",
        )


# --- validation ---------------------------------------------------------------------------


def _confidence(value: float | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    value = float(value)
    return min(1.0, max(0.0, value)) if math.isfinite(value) else None


def validate_words(
    raw: Iterable[TimedWord], *, audio_duration: float, tolerance: float
) -> tuple[tuple[TimedWord, ...], int]:
    """Normalized, ordered, non-overlapping words and the number of words dropped."""
    if not math.isfinite(audio_duration) or audio_duration < 0:
        raise TimingOutputError("The audio duration is invalid")
    words: list[TimedWord] = []
    rejected = 0
    previous_start = -math.inf
    for index, item in enumerate(raw):
        start, end = float(item.start), float(item.end)
        if not (math.isfinite(start) and math.isfinite(end)):
            raise TimingOutputError(f"Word {index} has a non-numeric timestamp")
        if start < -START_TOLERANCE:
            raise TimingOutputError(f"Word {index} starts before the audio ({start:.3f}s)")
        if start < previous_start - ORDER_TOLERANCE:
            raise TimingOutputError(f"Word {index} is out of order ({start:.3f}s)")
        if end > audio_duration + tolerance:
            raise TimingOutputError(
                f"Word {index} ends after the audio ({end:.3f}s > {audio_duration:.3f}s)"
            )
        previous_start = max(previous_start, start)
        start, end = max(0.0, start), min(end, audio_duration)
        text = _WHITESPACE.sub(" ", str(item.text)).strip()
        if not text or len(text) > MAX_WORD_CHARS or end - start < MIN_WORD_SECONDS:
            rejected += 1  # no usable interval or text: dropped, never given an invented time
            continue
        if words and start < words[-1].end:
            last = words[-1]
            if start - last.start < MIN_WORD_SECONDS:
                rejected += 1  # practically the same start as the previous word
                continue
            words[-1] = TimedWord(last.start, round(start, 3), last.text, last.confidence)
        words.append(TimedWord(round(start, 3), round(end, 3), text, _confidence(item.confidence)))
    return tuple(words), rejected
