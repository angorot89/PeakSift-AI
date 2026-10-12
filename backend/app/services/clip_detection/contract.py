"""The clip-analysis provider contract: request/result types, structured output, errors.

A provider receives one bounded *analysis window* of timestamped transcript lines and
returns the moments it considers worth clipping, as **raw** candidates. Raw means
untrusted: everything a provider returns is re-validated against the transcript timeline
and the configured bounds before it can become a database record (see ``validation.py``).

Provider SDK objects never leave the provider module; this module is the only vocabulary
the pipeline, the API and the tests share.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.clip_detection import (
    CANDIDATE_CATEGORIES,
    HOOK_MAX_LENGTH,
    RATIONALE_MAX_LENGTH,
    SCORE_MAX,
    SCORE_MIN,
    TITLE_MAX_LENGTH,
)

# --- transcript input ----------------------------------------------------------------


@dataclass(frozen=True)
class TranscriptLine:
    """One transcript segment in absolute seconds from the start of the video."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class AnalysisWindow:
    """A bounded slice of the transcript handed to the provider in one request."""

    index: int
    start: float
    end: float
    lines: tuple[TranscriptLine, ...]

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def char_count(self) -> int:
        return sum(len(line.text) for line in self.lines)


@dataclass(frozen=True)
class ClipAnalysisRequest:
    window: AnalysisWindow
    video_duration: float
    min_clip_seconds: float
    max_clip_seconds: float
    max_candidates: int
    language: str | None = None
    # Extra editorial guidance from server configuration; never from an API client.
    instructions: str | None = None


# --- provider output -----------------------------------------------------------------


@dataclass(frozen=True)
class RawCandidate:
    """Exactly what the model proposed, in absolute seconds. Untrusted until validated."""

    start: float
    end: float
    title: str
    hook: str
    rationale: str
    category: str
    hook_score: int
    entertainment_score: int
    clarity_score: int
    payoff_score: int
    completeness_score: int


@dataclass(frozen=True)
class ClipAnalysisResult:
    candidates: tuple[RawCandidate, ...]
    provider: str
    model: str


@dataclass(frozen=True)
class ProviderDiagnostics:
    """Whether a provider can serve requests right now, with a message safe to show users."""

    available: bool
    detail: str


@runtime_checkable
class ClipAnalysisProvider(Protocol):
    name: str
    model: str

    def analyze(self, request: ClipAnalysisRequest) -> ClipAnalysisResult: ...

    def check_availability(self) -> ProviderDiagnostics: ...


# --- structured output schema (shared by every provider) ---------------------------------


class CandidateOutput(BaseModel):
    """The JSON object a model must return for each proposed clip."""

    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(description="Absolute start time in seconds from the video start")
    end_seconds: float = Field(description="Absolute end time in seconds from the video start")
    title: str = Field(description="Short, specific title for the clip")
    hook: str = Field(description="One sentence describing why a viewer keeps watching")
    rationale: str = Field(description="Why this moment works as a standalone short clip")
    category: str = Field(
        description="One of: " + ", ".join(CANDIDATE_CATEGORIES),
    )
    hook_score: int = Field(description="0-100: strength of the opening")
    entertainment_score: int = Field(description="0-100: how entertaining or engaging it is")
    clarity_score: int = Field(description="0-100: understandable without prior context")
    payoff_score: int = Field(description="0-100: strength of the ending or punchline")
    completeness_score: int = Field(description="0-100: feels like a complete thought or story")


class AnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[CandidateOutput] = Field(description="Proposed clips; may be empty")


def analysis_output_json_schema() -> dict[str, Any]:
    """JSON schema for the structured response, usable as an OpenAI/Ollama format."""
    return AnalysisOutput.model_json_schema()


def parse_analysis_output(data: Any, *, provider: str) -> tuple[RawCandidate, ...]:
    """Turn a provider's decoded JSON into raw candidates, or raise ClipProviderOutputError.

    Only the *shape* is checked here (pydantic coerces "42" → 42 and 1 → 1.0). Timestamps,
    score ranges, text lengths and transcript alignment are judged later by validation,
    which has the transcript at hand.
    """
    try:
        output = AnalysisOutput.model_validate(data)
    except ValidationError as error:
        raise ClipProviderOutputError(
            f"{provider} returned a response that does not match the expected schema "
            f"({error.error_count()} problem(s))"
        ) from error
    return tuple(
        RawCandidate(
            start=item.start_seconds,
            end=item.end_seconds,
            title=item.title,
            hook=item.hook,
            rationale=item.rationale,
            category=item.category,
            hook_score=item.hook_score,
            entertainment_score=item.entertainment_score,
            clarity_score=item.clarity_score,
            payoff_score=item.payoff_score,
            completeness_score=item.completeness_score,
        )
        for item in output.candidates
    )


# Documented bounds, re-exported so callers do not need the model module.
SCORE_RANGE = (SCORE_MIN, SCORE_MAX)
TEXT_LIMITS = {
    "title": TITLE_MAX_LENGTH,
    "hook": HOOK_MAX_LENGTH,
    "rationale": RATIONALE_MAX_LENGTH,
}


# --- errors ------------------------------------------------------------------------------


class ClipProviderError(Exception):
    """A provider failed. ``code`` is stable; ``message`` is safe to store and show.

    ``retryable`` tells the pipeline whether a bounded retry makes sense (network blips,
    rate limits, timeouts, 5xx) or not (bad configuration, malformed output).
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ClipProviderConfigurationError(ClipProviderError):
    def __init__(self, message: str, *, code: str = "provider_configuration") -> None:
        super().__init__(code, message, retryable=False)


class ClipProviderUnavailableError(ClipProviderError):
    """The inference endpoint could not be reached or is not serving the model."""

    def __init__(self, message: str, *, code: str = "provider_unavailable") -> None:
        super().__init__(code, message, retryable=True)


class ClipProviderTimeoutError(ClipProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_timeout", message, retryable=True)


class ClipProviderRateLimitError(ClipProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_rate_limited", message, retryable=True)


class ClipProviderOutputError(ClipProviderError):
    """The model answered, but not with something PeakSift can trust."""

    def __init__(self, message: str) -> None:
        super().__init__("provider_output", message, retryable=False)
