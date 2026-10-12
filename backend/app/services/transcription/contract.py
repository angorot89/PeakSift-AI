"""The provider contract: request/result types, capabilities, errors and validation."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderSegment:
    """One timestamped piece of text, in seconds relative to the audio the provider saw."""

    start: float
    end: float
    text: str
    speaker: str | None = None  # reserved; no provider sets it in Milestone 3


@dataclass(frozen=True)
class ProviderTranscriptionResult:
    text: str
    language: str | None
    language_probability: float | None
    provider: str
    model: str
    segments: tuple[ProviderSegment, ...]


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_segment_timestamps: bool
    supports_word_timestamps: bool
    supports_language_detection: bool
    supports_diarization: bool


@dataclass(frozen=True)
class TranscriptionRequest:
    audio_path: Path
    language_hint: str | None = None
    # Short text from the preceding chunk, used only to steer the model; never persisted.
    prompt: str | None = None


@runtime_checkable
class TranscriptionProvider(Protocol):
    name: str
    model: str
    capabilities: ProviderCapabilities

    def transcribe(self, request: TranscriptionRequest) -> ProviderTranscriptionResult: ...


# --- errors -------------------------------------------------------------------------


class TranscriptionProviderError(Exception):
    """A provider failed. ``code`` is stable; ``message`` is safe to store and show.

    ``retryable`` tells the pipeline whether a bounded retry makes sense (network blips,
    rate limits) or not (bad configuration, invalid audio, malformed output).
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ProviderConfigurationError(TranscriptionProviderError):
    def __init__(self, message: str, *, code: str = "provider_configuration") -> None:
        super().__init__(code, message, retryable=False)


class ProviderCapabilityError(TranscriptionProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_capability", message, retryable=False)


class ProviderOutputError(TranscriptionProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_output", message, retryable=False)


# --- contract enforcement -------------------------------------------------------------


def require_segment_timestamps(provider: TranscriptionProvider) -> None:
    """The PeakSift pipeline cuts clips from segment times; refuse providers without them."""
    if not provider.capabilities.supports_segment_timestamps:
        raise ProviderCapabilityError(
            f"Provider '{provider.name}' with model '{provider.model}' does not return segment "
            "timestamps, which PeakSift requires. Timestamps are never fabricated."
        )


def validate_segments(segments: Iterable[ProviderSegment]) -> tuple[ProviderSegment, ...]:
    """Normalise provider segments and reject anything that cannot be trusted.

    - text is stripped; empty segments are dropped
    - start must be >= 0 and end must be > start
    - segments must be in non-decreasing start order
    Raises ProviderOutputError instead of silently "fixing" timestamps.
    """
    cleaned: list[ProviderSegment] = []
    previous_start = -1.0
    for index, segment in enumerate(segments):
        text = segment.text.strip()
        if not text:
            continue
        start, end = float(segment.start), float(segment.end)
        if start != start or end != end:  # NaN
            raise ProviderOutputError(f"Segment {index} has a non-numeric timestamp")
        if start < 0:
            raise ProviderOutputError(f"Segment {index} starts before 0 ({start:.3f}s)")
        if end <= start:
            raise ProviderOutputError(
                f"Segment {index} ends before it starts ({start:.3f}s -> {end:.3f}s)"
            )
        if start < previous_start:
            raise ProviderOutputError(f"Segment {index} is out of order ({start:.3f}s)")
        previous_start = start
        cleaned.append(ProviderSegment(start=start, end=end, text=text, speaker=segment.speaker))
    return tuple(cleaned)


def join_segment_text(segments: Iterable[ProviderSegment]) -> str:
    return " ".join(segment.text for segment in segments).strip()
