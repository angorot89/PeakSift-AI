import logging
import types
from pathlib import Path

import httpx
import openai
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services.transcription import openai_provider as provider_module
from app.services.transcription.contract import (
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderOutputError,
    TranscriptionProviderError,
    TranscriptionRequest,
)
from app.services.transcription.openai_provider import OpenAITranscriptionProvider

KEY = "sk-test-not-a-real-key-0000000000000000"
REQUEST = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")


def status_error(cls, status: int):
    return cls("error", response=httpx.Response(status, request=REQUEST), body=None)


class FakeTranscriptions:
    def __init__(self):
        self.calls: list[dict] = []
        self.response = types.SimpleNamespace(
            text="Hello there. General Kenobi.",
            language="english",
            duration=5.0,
            segments=[
                types.SimpleNamespace(start=0.0, end=2.5, text=" Hello there. "),
                types.SimpleNamespace(start=2.5, end=5.0, text="General Kenobi."),
            ],
        )
        self.raise_error: Exception | None = None

    def create(self, **kwargs):
        kwargs["file_name"] = Path(kwargs["file"].name).name
        kwargs["file_mode"] = kwargs["file"].mode
        self.calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        return self.response


class FakeOpenAI:
    instances: list["FakeOpenAI"] = []

    def __init__(self, *, api_key, timeout, max_retries):
        self.api_key, self.timeout, self.max_retries = api_key, timeout, max_retries
        self.audio = types.SimpleNamespace(transcriptions=FakeTranscriptions())
        FakeOpenAI.instances.append(self)


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.instances = []
    monkeypatch.setattr(provider_module.openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(get_settings(), "openai_api_key", SecretStr(KEY))
    monkeypatch.setattr(get_settings(), "openai_timestamp_model", "whisper-1")
    return FakeOpenAI


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "0003.mp3"
    path.write_bytes(b"mp3" * 100)
    return path


def provider() -> OpenAITranscriptionProvider:
    return OpenAITranscriptionProvider(get_settings())


# --- configuration -----


def test_missing_key_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", None)

    with pytest.raises(ProviderConfigurationError) as excinfo:
        provider()

    assert excinfo.value.code == "missing_api_key"
    assert "OPENAI_API_KEY" in excinfo.value.message


def test_empty_key_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", SecretStr(""))

    with pytest.raises(ProviderConfigurationError):
        provider()


@pytest.mark.parametrize("model", ["gpt-4o-mini-transcribe", "gpt-4o-transcribe"])
def test_text_only_model_cannot_be_the_timestamp_model(fake_openai, monkeypatch, model):
    monkeypatch.setattr(get_settings(), "openai_timestamp_model", model)

    with pytest.raises(ProviderCapabilityError) as excinfo:
        provider()

    assert model in str(excinfo.value) and "whisper-1" in str(excinfo.value)
    assert "never fabricates" in str(excinfo.value)


def test_client_is_built_with_key_timeout_and_minimal_retries(fake_openai, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_timeout_seconds", 42.0)

    p = provider()

    assert p.name == "openai" and p.model == "whisper-1"
    assert p.capabilities.supports_segment_timestamps and not p.capabilities.supports_diarization
    client = fake_openai.instances[-1]
    assert client.api_key == KEY and client.timeout == 42.0 and client.max_retries == 1


def test_constructing_the_provider_makes_no_request(fake_openai):
    provider()

    assert fake_openai.instances[-1].audio.transcriptions.calls == []


# --- requests -----


def test_request_uses_verbose_json_segments_and_passes_hints(fake_openai, audio):
    p = provider()

    p.transcribe(TranscriptionRequest(audio_path=audio, language_hint="fr", prompt="context"))
    call = fake_openai.instances[-1].audio.transcriptions.calls[0]

    assert call["model"] == "whisper-1"
    assert call["response_format"] == "verbose_json"
    assert call["timestamp_granularities"] == ["segment"]
    assert call["language"] == "fr" and call["prompt"] == "context"
    assert call["file_name"] == "0003.mp3" and call["file_mode"] == "rb"


def test_hints_are_omitted_when_absent(fake_openai, audio):
    provider().transcribe(TranscriptionRequest(audio_path=audio))
    call = fake_openai.instances[-1].audio.transcriptions.calls[0]

    assert "language" not in call and "prompt" not in call


def test_response_is_normalised(fake_openai, audio):
    result = provider().transcribe(TranscriptionRequest(audio_path=audio))

    assert result.provider == "openai" and result.model == "whisper-1"
    assert result.text == "Hello there. General Kenobi."
    assert result.language == "english" and result.language_probability is None
    assert [(s.start, s.end, s.text) for s in result.segments] == [
        (0.0, 2.5, "Hello there."),
        (2.5, 5.0, "General Kenobi."),
    ]


def test_full_text_falls_back_to_segments(fake_openai, audio):
    fake = fake_openai
    p = provider()
    fake.instances[-1].audio.transcriptions.response.text = ""

    assert (
        p.transcribe(TranscriptionRequest(audio_path=audio)).text == "Hello there. General Kenobi."
    )


# --- output validation -----


def test_response_without_segments_is_rejected(fake_openai, audio):
    p = provider()
    fake_openai.instances[-1].audio.transcriptions.response = types.SimpleNamespace(
        text="only text"
    )

    with pytest.raises(ProviderOutputError) as excinfo:
        p.transcribe(TranscriptionRequest(audio_path=audio))

    assert "no segment timestamps" in str(excinfo.value)


def test_malformed_segments_are_rejected(fake_openai, audio):
    p = provider()
    fake_openai.instances[-1].audio.transcriptions.response.segments = [
        types.SimpleNamespace(start=4.0, end=1.0, text="backwards")
    ]

    with pytest.raises(ProviderOutputError):
        p.transcribe(TranscriptionRequest(audio_path=audio))


def test_segments_with_wrong_shape_are_rejected(fake_openai, audio):
    p = provider()
    fake_openai.instances[-1].audio.transcriptions.response.segments = [{"start": "x"}]

    with pytest.raises(ProviderOutputError):
        p.transcribe(TranscriptionRequest(audio_path=audio))


# --- size guard -----


def test_oversized_chunk_is_refused_before_upload(fake_openai, audio, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_max_upload_bytes", 100)
    p = provider()

    with pytest.raises(TranscriptionProviderError) as excinfo:
        p.transcribe(TranscriptionRequest(audio_path=audio))

    assert excinfo.value.code == "audio_too_large" and excinfo.value.retryable is False
    assert fake_openai.instances[-1].audio.transcriptions.calls == []


def test_missing_audio_file(fake_openai, tmp_path):
    with pytest.raises(TranscriptionProviderError) as excinfo:
        provider().transcribe(TranscriptionRequest(audio_path=tmp_path / "nope.mp3"))

    assert excinfo.value.code == "audio_missing"


# --- error mapping -----


@pytest.mark.parametrize(
    ("error", "expected_code", "retryable", "expected_type"),
    [
        (
            status_error(openai.AuthenticationError, 401),
            "openai_authentication",
            False,
            ProviderConfigurationError,
        ),
        (
            status_error(openai.PermissionDeniedError, 403),
            "openai_permission",
            False,
            ProviderConfigurationError,
        ),
        (
            status_error(openai.RateLimitError, 429),
            "openai_rate_limited",
            True,
            TranscriptionProviderError,
        ),
        (
            openai.APITimeoutError(request=REQUEST),
            "openai_unreachable",
            True,
            TranscriptionProviderError,
        ),
        (
            openai.APIConnectionError(request=REQUEST),
            "openai_unreachable",
            True,
            TranscriptionProviderError,
        ),
        (
            status_error(openai.InternalServerError, 503),
            "openai_server_error",
            True,
            TranscriptionProviderError,
        ),
        (
            status_error(openai.BadRequestError, 400),
            "openai_request_rejected",
            False,
            TranscriptionProviderError,
        ),
    ],
)
def test_sdk_errors_are_normalised(
    fake_openai, audio, error, expected_code, retryable, expected_type
):
    p = provider()
    fake_openai.instances[-1].audio.transcriptions.raise_error = error

    with pytest.raises(expected_type) as excinfo:
        p.transcribe(TranscriptionRequest(audio_path=audio))

    assert excinfo.value.code == expected_code
    assert excinfo.value.retryable is retryable
    assert KEY not in excinfo.value.message


def test_key_never_appears_in_errors_or_logs(fake_openai, audio, caplog):
    p = provider()
    fake_openai.instances[-1].audio.transcriptions.raise_error = openai.OpenAIError(f"boom {KEY}")

    with caplog.at_level(logging.DEBUG), pytest.raises(TranscriptionProviderError) as excinfo:
        p.transcribe(TranscriptionRequest(audio_path=audio))

    assert KEY not in excinfo.value.message
    assert KEY not in caplog.text
