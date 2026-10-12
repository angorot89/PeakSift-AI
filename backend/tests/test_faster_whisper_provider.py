import os
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.transcription import faster_whisper as provider_module
from app.services.transcription.contract import (
    ProviderConfigurationError,
    ProviderOutputError,
    TranscriptionProviderError,
    TranscriptionRequest,
)
from app.services.transcription.faster_whisper import FasterWhisperProvider


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str


@dataclass
class FakeInfo:
    language: str = "en"
    language_probability: float = 0.93
    duration: float = 5.0


class FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel; records construction and calls."""

    constructed: list[tuple] = []
    next_segments: list[FakeSegment] = [
        FakeSegment(0.0, 2.0, " Hello "),
        FakeSegment(2.0, 5.0, "world"),
    ]
    next_info: FakeInfo = FakeInfo()
    raise_on_transcribe: Exception | None = None

    def __init__(self, model, device, compute_type):
        FakeWhisperModel.constructed.append((model, device, compute_type))
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        if FakeWhisperModel.raise_on_transcribe:
            raise FakeWhisperModel.raise_on_transcribe
        return iter(FakeWhisperModel.next_segments), FakeWhisperModel.next_info


@pytest.fixture
def fake_whisper(monkeypatch):
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(provider_module, "_MODEL_CACHE", {})
    FakeWhisperModel.constructed = []
    FakeWhisperModel.next_segments = [
        FakeSegment(0.0, 2.0, " Hello "),
        FakeSegment(2.0, 5.0, "world"),
    ]
    FakeWhisperModel.next_info = FakeInfo()
    FakeWhisperModel.raise_on_transcribe = None
    return FakeWhisperModel


def request(tmp_path: Path, **kwargs) -> TranscriptionRequest:
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"mp3")
    return TranscriptionRequest(audio_path=audio, **kwargs)


# --- lazy loading and options -----------------------------------------------------


def test_constructing_the_provider_does_not_load_a_model(fake_whisper):
    provider = FasterWhisperProvider(get_settings())

    assert provider.name == "faster_whisper" and provider.model == "small"
    assert provider.capabilities.supports_segment_timestamps
    assert not provider.capabilities.supports_diarization
    assert fake_whisper.constructed == []


def test_model_is_loaded_once_with_configured_options(fake_whisper, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "faster_whisper_model", "medium")
    monkeypatch.setattr(get_settings(), "faster_whisper_device", "cpu")
    monkeypatch.setattr(get_settings(), "faster_whisper_compute_type", "int8")
    monkeypatch.setattr(get_settings(), "faster_whisper_beam_size", 3)
    provider = FasterWhisperProvider(get_settings())

    provider.transcribe(request(tmp_path, language_hint="fr", prompt="previous words"))
    provider.transcribe(request(tmp_path))
    FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))  # another instance

    assert fake_whisper.constructed == [("medium", "cpu", "int8")]
    model = provider_module._MODEL_CACHE[("medium", "cpu", "int8")]
    assert len(model.calls) == 3
    first = model.calls[0]
    assert first["audio"].endswith("chunk.mp3")
    assert first["beam_size"] == 3
    assert first["language"] == "fr"
    assert first["initial_prompt"] == "previous words"
    assert model.calls[1]["language"] is None and model.calls[1]["initial_prompt"] is None


# --- output normalisation -------------------------------------------------------------


def test_segments_language_and_text_are_normalised(fake_whisper, tmp_path):
    result = FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))

    assert result.provider == "faster_whisper" and result.model == "small"
    assert result.language == "en" and result.language_probability == 0.93
    assert [(s.start, s.end, s.text) for s in result.segments] == [
        (0.0, 2.0, "Hello"),
        (2.0, 5.0, "world"),
    ]
    assert result.text == "Hello world"
    assert all(s.speaker is None for s in result.segments)


def test_silent_audio_yields_an_empty_result(fake_whisper, tmp_path):
    fake_whisper.next_segments = []

    result = FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))

    assert result.segments == () and result.text == ""
    assert result.language == "en"


def test_malformed_segments_are_rejected(fake_whisper, tmp_path):
    fake_whisper.next_segments = [FakeSegment(3.0, 1.0, "backwards")]

    with pytest.raises(ProviderOutputError):
        FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))


def test_missing_language_info_is_tolerated(fake_whisper, tmp_path):
    fake_whisper.next_info = types.SimpleNamespace()

    result = FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))

    assert result.language is None and result.language_probability is None


# --- failures ---------------------------------------------------------------------------


def test_model_exceptions_are_normalised_without_leaking_paths(fake_whisper, tmp_path):
    fake_whisper.raise_on_transcribe = RuntimeError("ctranslate2 error at /Users/dev/.cache/x")

    with pytest.raises(TranscriptionProviderError) as excinfo:
        FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))

    assert excinfo.value.code == "provider_failure"
    assert excinfo.value.retryable is False
    assert "/Users" not in excinfo.value.message
    assert "RuntimeError" in excinfo.value.message


def test_missing_audio_file(fake_whisper, tmp_path):
    fake_whisper.raise_on_transcribe = FileNotFoundError("/private/tmp/chunk.mp3")

    with pytest.raises(TranscriptionProviderError) as excinfo:
        FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))

    assert excinfo.value.code == "audio_missing"
    assert "/private" not in excinfo.value.message


def test_model_load_failure_is_a_configuration_error(monkeypatch, tmp_path):
    class Exploding:
        def __init__(self, *a, **k):
            raise ValueError("Invalid model size 'nope' at /Users/dev/.cache/huggingface")

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = Exploding
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(provider_module, "_MODEL_CACHE", {})
    monkeypatch.setattr(get_settings(), "faster_whisper_model", "nope")

    with pytest.raises(ProviderConfigurationError) as excinfo:
        FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))

    assert excinfo.value.code == "model_load_failed"
    assert "nope" in excinfo.value.message and "/Users" not in excinfo.value.message


def test_missing_dependency_is_a_configuration_error(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import raises ImportError
    monkeypatch.setattr(provider_module, "_MODEL_CACHE", {})

    with pytest.raises(ProviderConfigurationError) as excinfo:
        FasterWhisperProvider(get_settings()).transcribe(request(tmp_path))

    assert excinfo.value.code == "provider_missing"


# --- real model (opt-in: downloads the "tiny" model, needs macOS `say`) --------------------


@pytest.mark.skipif(
    not os.environ.get("PEAKSIFT_REAL_WHISPER") or shutil.which("say") is None,
    reason="set PEAKSIFT_REAL_WHISPER=1 on macOS to run the real tiny-model check",
)
def test_real_tiny_model_transcribes_generated_speech(tmp_path, monkeypatch):
    aiff = tmp_path / "speech.aiff"
    subprocess.run(
        ["say", "-o", str(aiff), "Hello world. This is a PeakSift transcription test."], check=True
    )
    mp3 = tmp_path / "speech.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(aiff),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(mp3),
        ],
        check=True,
    )
    monkeypatch.setattr(get_settings(), "faster_whisper_model", "tiny")
    monkeypatch.setattr(provider_module, "_MODEL_CACHE", {})

    result = FasterWhisperProvider(get_settings()).transcribe(TranscriptionRequest(audio_path=mp3))

    assert result.model == "tiny" and result.language == "en"
    assert "hello" in result.text.lower()
    assert result.segments and result.segments[0].start >= 0
    assert result.segments[-1].end <= 10
