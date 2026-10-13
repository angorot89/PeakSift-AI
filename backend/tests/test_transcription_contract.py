from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.transcription import factory
from app.services.transcription.contract import (
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderOutputError,
    ProviderSegment,
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionRequest,
    join_segment_text,
    require_segment_timestamps,
    validate_segments,
)
from tests.fakes import TEXT_ONLY_CAPABILITIES, FakeProvider

# --- types -----


def test_result_types_are_immutable_and_provider_agnostic():
    segment = ProviderSegment(start=1.0, end=2.0, text="hi")
    with pytest.raises(FrozenInstanceError):
        segment.start = 5.0  # type: ignore[misc]
    assert segment.speaker is None

    provider = FakeProvider()
    result = provider.transcribe(TranscriptionRequest(audio_path=Path("/tmp/x.mp3")))
    assert isinstance(provider, TranscriptionProvider)
    assert result.provider == "fake" and result.model == "fake-1"
    assert result.text == "Hello there. General Kenobi."
    assert [s.start for s in result.segments] == [0.0, 2.5]


def test_request_carries_hints_without_persisting_anything():
    request = TranscriptionRequest(audio_path=Path("a.mp3"), language_hint="fr", prompt="context")
    assert (request.language_hint, request.prompt) == ("fr", "context")


# --- errors -----


def test_error_hierarchy_and_retryable_flag():
    transient = TranscriptionProviderError("rate_limited", "Too many requests", retryable=True)
    assert transient.retryable is True and transient.code == "rate_limited"
    assert str(transient) == "Too many requests"

    for error in (
        ProviderConfigurationError("bad config"),
        ProviderCapabilityError("no timestamps"),
        ProviderOutputError("garbage"),
    ):
        assert isinstance(error, TranscriptionProviderError)
        assert error.retryable is False
    assert ProviderConfigurationError("x").code == "provider_configuration"
    assert ProviderCapabilityError("x").code == "provider_capability"
    assert ProviderOutputError("x").code == "provider_output"


# --- capability enforcement -----


def test_timestamp_capable_provider_is_accepted():
    require_segment_timestamps(FakeProvider())


def test_text_only_provider_is_refused_with_a_clear_message():
    provider = FakeProvider(name="texty", model="text-only", capabilities=TEXT_ONLY_CAPABILITIES)

    with pytest.raises(ProviderCapabilityError) as excinfo:
        require_segment_timestamps(provider)

    assert "texty" in str(excinfo.value) and "text-only" in str(excinfo.value)
    assert "never fabricated" in str(excinfo.value)


# --- segment validation -----


def test_validate_segments_strips_text_and_drops_empty_segments():
    segments = validate_segments(
        [
            ProviderSegment(0.0, 1.0, "  Hello  "),
            ProviderSegment(1.0, 1.5, "   "),
            ProviderSegment(1.5, 2.0, "world"),
        ]
    )

    assert [s.text for s in segments] == ["Hello", "world"]
    assert segments[0].start == 0.0 and segments[1].end == 2.0
    assert join_segment_text(segments) == "Hello world"


def test_validate_segments_keeps_speaker_and_order():
    segments = validate_segments(
        [ProviderSegment(0.0, 1.0, "a", speaker="S1"), ProviderSegment(1.0, 3.0, "b")]
    )
    assert segments[0].speaker == "S1" and segments[1].speaker is None


@pytest.mark.parametrize(
    ("bad", "fragment"),
    [
        ([ProviderSegment(-0.1, 1.0, "x")], "before 0"),
        ([ProviderSegment(2.0, 2.0, "x")], "ends before it starts"),
        ([ProviderSegment(3.0, 1.0, "x")], "ends before it starts"),
        ([ProviderSegment(5.0, 6.0, "a"), ProviderSegment(1.0, 2.0, "b")], "out of order"),
        ([ProviderSegment(float("nan"), 1.0, "x")], "non-numeric"),
    ],
)
def test_validate_segments_rejects_untrustworthy_timestamps(bad, fragment):
    with pytest.raises(ProviderOutputError) as excinfo:
        validate_segments(bad)
    assert fragment in str(excinfo.value)


def test_validate_segments_allows_touching_and_overlapping_starts_in_order():
    segments = validate_segments(
        [
            ProviderSegment(0.0, 2.0, "a"),
            ProviderSegment(1.8, 3.0, "b"),
            ProviderSegment(3.0, 4.0, "c"),
        ]
    )
    assert len(segments) == 3


def test_validate_segments_empty_input():
    assert validate_segments([]) == ()
    assert join_segment_text(()) == ""


# --- factory -----


def test_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "transcription_provider", "deepgram")

    with pytest.raises(ProviderConfigurationError) as excinfo:
        factory.get_transcription_provider()

    assert "deepgram" in str(excinfo.value)
    assert "faster_whisper" in str(excinfo.value) and "openai" in str(excinfo.value)


def test_factory_supported_names():
    assert set(factory.PROVIDER_REGISTRY) == {"faster_whisper", "openai"}


def test_factory_builds_registered_provider_and_enforces_capabilities(monkeypatch):
    monkeypatch.setitem(factory.PROVIDER_REGISTRY, "fake", "tests.fakes:FakeProvider")
    monkeypatch.setattr(get_settings(), "transcription_provider", "fake")

    provider = factory.get_transcription_provider()

    assert isinstance(provider, FakeProvider)


def test_factory_refuses_registered_provider_without_timestamps(monkeypatch):
    class TextOnly(FakeProvider):
        def __init__(self, settings):
            super().__init__(name="text-only", capabilities=TEXT_ONLY_CAPABILITIES)

    monkeypatch.setattr("tests.fakes.TextOnlyForFactory", TextOnly, raising=False)
    monkeypatch.setitem(factory.PROVIDER_REGISTRY, "textonly", "tests.fakes:TextOnlyForFactory")
    monkeypatch.setattr(get_settings(), "transcription_provider", "textonly")

    with pytest.raises(ProviderCapabilityError):
        factory.get_transcription_provider()


def test_factory_reports_missing_provider_module(monkeypatch):
    monkeypatch.setitem(
        factory.PROVIDER_REGISTRY, "ghost", "app.services.transcription.ghost:Ghost"
    )
    monkeypatch.setattr(get_settings(), "transcription_provider", "ghost")

    with pytest.raises(ProviderConfigurationError) as excinfo:
        factory.get_transcription_provider()

    assert "ghost" in str(excinfo.value)
