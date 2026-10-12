"""Test doubles shared across the transcription and clip detection tests. Never used in
production."""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.services.clip_detection.contract import (
    ClipAnalysisRequest,
    ClipAnalysisResult,
    ProviderDiagnostics,
    RawCandidate,
)
from app.services.transcription.contract import (
    ProviderCapabilities,
    ProviderSegment,
    ProviderTranscriptionResult,
    TranscriptionRequest,
)

FULL_CAPABILITIES = ProviderCapabilities(
    supports_segment_timestamps=True,
    supports_word_timestamps=False,
    supports_language_detection=True,
    supports_diarization=False,
)

TEXT_ONLY_CAPABILITIES = ProviderCapabilities(
    supports_segment_timestamps=False,
    supports_word_timestamps=False,
    supports_language_detection=True,
    supports_diarization=False,
)


@dataclass
class FakeProvider:
    """Returns canned segments relative to each request; records what it was asked."""

    name: str = "fake"
    model: str = "fake-1"
    capabilities: ProviderCapabilities = FULL_CAPABILITIES
    segments: tuple[ProviderSegment, ...] = (
        ProviderSegment(0.0, 2.5, "Hello there."),
        ProviderSegment(2.5, 5.0, "General Kenobi."),
    )
    language: str | None = "en"
    language_probability: float | None = 0.98
    requests: list[TranscriptionRequest] = field(default_factory=list)

    def transcribe(self, request: TranscriptionRequest) -> ProviderTranscriptionResult:
        self.requests.append(request)
        return ProviderTranscriptionResult(
            text=" ".join(s.text for s in self.segments),
            language=self.language,
            language_probability=self.language_probability,
            provider=self.name,
            model=self.model,
            segments=self.segments,
        )


def raw_candidate(start: float, end: float, **overrides) -> RawCandidate:
    """A plausible model proposal; override any field to make it invalid."""
    fields = {
        "start": start,
        "end": end,
        "title": f"Moment at {start:.0f}s",
        "hook": "Wait for the ending.",
        "rationale": "A self-contained story with a clear payoff.",
        "category": "story",
        "hook_score": 80,
        "entertainment_score": 75,
        "clarity_score": 70,
        "payoff_score": 85,
        "completeness_score": 78,
    }
    fields.update(overrides)
    return RawCandidate(**fields)


@dataclass
class FakeClipProvider:
    """Returns canned candidates per window; records every request it received.

    ``respond`` can replace the canned answer: it receives the request and returns the
    candidates (or raises) so tests can script per-window behaviour and failures.
    """

    name: str = "fake"
    model: str = "fake-clips-1"
    candidates: tuple[RawCandidate, ...] = ()
    respond: Callable[[ClipAnalysisRequest], tuple[RawCandidate, ...]] | None = None
    available: bool = True
    requests: list[ClipAnalysisRequest] = field(default_factory=list)

    def analyze(self, request: ClipAnalysisRequest) -> ClipAnalysisResult:
        self.requests.append(request)
        candidates = self.respond(request) if self.respond else self.candidates
        return ClipAnalysisResult(
            candidates=tuple(candidates), provider=self.name, model=self.model
        )

    def check_availability(self) -> ProviderDiagnostics:
        return ProviderDiagnostics(
            available=self.available, detail="ready" if self.available else "offline"
        )
