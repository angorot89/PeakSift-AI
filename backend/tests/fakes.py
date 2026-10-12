"""Test doubles shared across the transcription tests. Never used in production."""

from dataclasses import dataclass, field

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
