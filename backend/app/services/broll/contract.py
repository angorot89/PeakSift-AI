"""The B-roll suggestion provider contract: request/result types, structured output, errors.

A provider reads one clip's timestamped transcript (clip-local seconds) and proposes a few
moments where a supporting visual would help, as **raw** suggestions. Raw means untrusted:
everything is re-checked by ``validation.py`` (timing, text, score, duplicates, density) and
``grounding.py`` (the query must come from what was said) before it can be stored.

Provider SDK or HTTP objects never leave the provider module; this module is the only
vocabulary the pipeline and the tests share.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.broll.validation import RawSuggestion


@dataclass(frozen=True)
class TranscriptLine:
    """One transcript line, in clip-local seconds (0 = the clip's first frame)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class BrollRequest:
    lines: tuple[TranscriptLine, ...]
    clip_duration: float
    max_suggestions: int
    min_seconds: float
    max_seconds: float
    # The clip candidate's own title and hook (context only; never shown as a quotation).
    title: str | None = None
    hook: str | None = None
    language: str | None = None

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


@dataclass(frozen=True)
class BrollResult:
    suggestions: tuple[RawSuggestion, ...]
    provider: str
    model: str


@runtime_checkable
class BrollProvider(Protocol):
    name: str
    model: str

    def suggest(self, request: BrollRequest) -> BrollResult: ...


# --- structured output (the JSON a model must return) -------------------------------------


class SuggestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(description="When the visual starts, seconds from the clip start")
    end_seconds: float = Field(description="When the visual ends, seconds from the clip start")
    query: str = Field(description="What to show, 2-6 words, using things actually said")
    reason: str = Field(description="One short sentence: which line it supports and why")
    score: int = Field(description="0-100: how much the visual would help")


class SuggestionsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: list[SuggestionOutput] = Field(description="Few, specific moments; may be empty")


def suggestions_json_schema() -> dict[str, Any]:
    return SuggestionsOutput.model_json_schema()


def parse_suggestions(data: Any, *, provider: str) -> tuple[RawSuggestion, ...]:
    """Decoded JSON → raw suggestions, or BrollProviderOutputError when the shape is wrong.
    Only the shape is checked here; values are judged by validation and grounding."""
    try:
        output = SuggestionsOutput.model_validate(data)
    except ValidationError as error:
        raise BrollProviderOutputError(
            f"{provider} returned a response that does not match the expected schema "
            f"({error.error_count()} problem(s))"
        ) from error
    return tuple(
        RawSuggestion(
            start=item.start_seconds,
            end=item.end_seconds,
            query=item.query,
            reason=item.reason,
            score=item.score,
        )
        for item in output.suggestions
    )


# --- errors ------------------------------------------------------------------------------------


class BrollProviderError(Exception):
    """A provider failed. ``code`` is stable; ``message`` is safe to store and show.

    ``fallback_ok`` says whether the deterministic fallback may stand in (the provider could
    not answer: unreachable, timed out, overloaded, malformed answer) — never for a
    configuration mistake an operator must fix.
    """

    def __init__(self, code: str, message: str, *, fallback_ok: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fallback_ok = fallback_ok


class BrollProviderUnavailableError(BrollProviderError):
    def __init__(self, message: str, *, code: str = "provider_unavailable") -> None:
        super().__init__(code, message)


class BrollProviderTimeoutError(BrollProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_timeout", message)


class BrollProviderOutputError(BrollProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_output", message)


class BrollProviderConfigurationError(BrollProviderError):
    def __init__(self, message: str, *, code: str = "provider_configuration") -> None:
        super().__init__(code, message, fallback_ok=False)
