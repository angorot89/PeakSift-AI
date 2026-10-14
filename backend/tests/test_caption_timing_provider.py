"""Caption timing: the provider contract, output validation and the faster-whisper word
timing provider (a fake model; the real one is an opt-in local check)."""

import math
import os
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from app.core.config import Settings, get_settings
from app.services.caption_timing.contract import (
    MIN_WORD_SECONDS,
    CaptionTimingError,
    CaptionTimingProvider,
    CaptionTimingRequest,
    TimedWord,
    TimingCapabilities,
    TimingOutputError,
    TimingUnavailable,
    require_word_timestamps,
    validate_words,
)
from app.services.caption_timing.factory import get_timing_provider
from app.services.caption_timing.faster_whisper import FasterWhisperWordTimingProvider
from app.services.transcription import faster_whisper as whisper_runtime
from app.services.transcription.contract import (
    ProviderConfigurationError,
    TranscriptionProviderError,
)


def w(start, end, text="word", confidence=0.9):
    return TimedWord(start, end, text, confidence)


def check(words, duration=10.0, tolerance=0.25):
    return validate_words(words, audio_duration=duration, tolerance=tolerance)


# --- validation -----


def test_valid_words_are_kept_exactly_and_rounded():
    words, rejected = check(
        [w(0.0, 0.42, " C'était ", 0.81), w(0.5, 0.91, "مرحبا", 0.7), w(1.0, 1.3, "🔥")]
    )
    assert rejected == 0
    assert [x.text for x in words] == ["C'était", "مرحبا", "🔥"]
    assert words[0] == TimedWord(0.0, 0.42, "C'était", 0.81)


@pytest.mark.parametrize(
    "bad",
    [
        [w(math.nan, 1.0)],
        [w(0.0, math.inf)],
        [w(-0.5, 0.2)],  # starts before the audio
        [w(2.0, 2.5), w(1.0, 1.5)],  # out of order
        [w(9.0, 10.6)],  # ends materially after the 10 s audio
    ],
)
def test_untrustworthy_output_is_refused(bad):
    with pytest.raises(TimingOutputError):
        check(bad)


def test_words_without_a_usable_interval_or_text_are_dropped_and_counted():
    words, rejected = check(
        [
            w(0.0, 0.3, "one"),
            w(0.4, 0.4, "zero"),
            w(0.5, 0.45, "backwards"),
            w(0.6, 0.9, "   "),
            w(1.0, 1.3, "two"),
        ]
    )
    assert [x.text for x in words] == ["one", "two"] and rejected == 3


def test_tiny_irregularities_are_normalized_with_documented_tolerances():
    words, rejected = check(
        [w(-0.005, 0.3, "a"), w(0.25, 0.6, "b"), w(0.6, 0.9, "c"), w(9.5, 10.2, "d")]
    )
    assert rejected == 0
    assert words[0].start == 0.0  # a start just below 0 becomes 0
    assert words[0].end == 0.25  # overlap: the previous word ends where the next starts
    assert words[-1].end == 10.0  # within the tolerance: clamped to the audio
    assert all(a.end <= b.start for a, b in zip(words, words[1:], strict=False))
    assert all(x.end - x.start >= MIN_WORD_SECONDS for x in words)


def test_duplicate_start_times_keep_one_word():
    words, rejected = check([w(1.0, 1.4, "same"), w(1.0, 1.5, "again")])
    assert [x.text for x in words] == ["same"] and rejected == 1


def test_confidence_is_bounded_or_unknown():
    words, _ = check([w(0, 0.3, "a", 1.2), w(0.4, 0.7, "b", math.nan), w(0.8, 1.0, "c", None)])
    assert [x.confidence for x in words] == [1.0, None, None]


def test_empty_output_is_valid_and_too_long_tokens_are_dropped():
    assert check([]) == ((), 0)
    words, rejected = check([w(0.0, 0.5, "x" * 200), w(0.6, 0.9, "ok")])
    assert [x.text for x in words] == ["ok"] and rejected == 1


# --- contract and factory -----


class NoWords:
    name, model = "segments_only", "m"
    capabilities = TimingCapabilities(
        word_timestamps=False, language_detection=True, confidence=False
    )

    def time_words(self, request):  # pragma: no cover - never called
        raise AssertionError


def test_providers_without_word_timestamps_are_refused():
    assert isinstance(NoWords(), CaptionTimingProvider)
    with pytest.raises(TimingUnavailable) as info:
        require_word_timestamps(NoWords())
    assert info.value.code == "provider_capability"


def test_factory_builds_the_configured_provider_without_loading_a_model(monkeypatch):
    monkeypatch.setattr(whisper_runtime, "_MODEL_CACHE", {})
    provider = get_timing_provider(get_settings())
    assert isinstance(provider, FasterWhisperWordTimingProvider)
    assert (
        provider.capabilities.word_timestamps
        and provider.model == get_settings().faster_whisper_model
    )
    assert whisper_runtime._MODEL_CACHE == {}
    require_word_timestamps(provider)


def test_importing_the_app_and_worker_loads_no_speech_model():
    code = (
        "import sys; import app.main, app.workers.celery_app, app.services.caption_timing.factory;"
        "from app.services.transcription import faster_whisper as r;"
        "assert r._MODEL_CACHE == {}, 'a model was loaded';"
        "assert 'faster_whisper' not in sys.modules, 'faster_whisper was imported'"
    )
    subprocess.run(
        [sys.executable, "-c", code], check=True, cwd=Path(__file__).resolve().parents[1]
    )


# --- faster-whisper provider (fake model) -----


@dataclass
class FakeWord:
    start: float
    end: float
    word: str
    probability: float


@dataclass
class FakeSegment:
    words: list = field(default_factory=list)


@dataclass
class FakeInfo:
    language: str = "en"
    language_probability: float = 0.97


class FakeModel:
    constructed: list = []
    segments: list = []
    error: Exception | None = None

    def __init__(self, model, device, compute_type):
        FakeModel.constructed.append((model, device, compute_type))
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        if FakeModel.error:
            raise FakeModel.error
        return iter(FakeModel.segments), FakeInfo()


@pytest.fixture
def fake_model(monkeypatch):
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(whisper_runtime, "_MODEL_CACHE", {})
    FakeModel.constructed, FakeModel.error = [], None
    FakeModel.segments = [
        FakeSegment([FakeWord(0.1, 0.4, " Hello", 0.95), FakeWord(0.45, 0.9, " world.", 0.9)]),
        FakeSegment([FakeWord(1.2, 1.5, " Again", 0.8)]),
        FakeSegment([]),  # a segment without words
    ]
    seconds = {"value": 2.0}

    def decode(path, ffmpeg_path):
        return np.zeros(int(seconds["value"] * whisper_runtime.SAMPLE_RATE), dtype=np.float32)

    monkeypatch.setattr(whisper_runtime, "_decode_pcm", decode)
    FakeModel.seconds = seconds
    return FakeModel


def settings(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


def test_provider_returns_validated_clip_relative_words(fake_model, tmp_path):
    provider = FasterWhisperWordTimingProvider(
        settings(faster_whisper_model="tiny", faster_whisper_beam_size=2)
    )
    result = provider.time_words(CaptionTimingRequest(tmp_path / "clip.mp4", language_hint="en"))
    assert [x.text for x in result.words] == ["Hello", "world.", "Again"]
    assert result.words[0] == TimedWord(0.1, 0.4, "Hello", 0.95)
    assert result.language == "en" and result.language_probability == 0.97
    assert result.audio_duration == 2.0 and result.rejected_words == 0
    assert result.provider == "faster_whisper" and result.model == "tiny"
    call = whisper_runtime._MODEL_CACHE[
        ("tiny", get_settings().faster_whisper_device, get_settings().faster_whisper_compute_type)
    ].calls[0]
    assert call["word_timestamps"] is True and call["language"] == "en" and call["beam_size"] == 2


def test_the_model_is_loaded_lazily_once_and_shared(fake_model, tmp_path):
    provider = FasterWhisperWordTimingProvider(get_settings())
    assert fake_model.constructed == []
    provider.time_words(CaptionTimingRequest(tmp_path / "a.mp4"))
    FasterWhisperWordTimingProvider(get_settings()).time_words(
        CaptionTimingRequest(tmp_path / "b.mp4")
    )
    assert (
        len(fake_model.constructed) == 1
    )  # one model per worker process, shared with transcription


def test_silence_or_empty_audio_gives_no_words(fake_model, tmp_path):
    fake_model.segments = []
    result = FasterWhisperWordTimingProvider(get_settings()).time_words(
        CaptionTimingRequest(tmp_path / "a.mp4")
    )
    assert result.words == () and result.rejected_words == 0
    fake_model.seconds["value"] = 0.0
    result = FasterWhisperWordTimingProvider(get_settings()).time_words(
        CaptionTimingRequest(tmp_path / "a.mp4")
    )
    assert result.words == () and result.audio_duration == 0.0


def test_model_exceptions_become_safe_failures(fake_model, tmp_path):
    fake_model.error = RuntimeError("CUDA out of memory at /secret/path/model.bin")
    with pytest.raises(CaptionTimingError) as info:
        FasterWhisperWordTimingProvider(get_settings()).time_words(
            CaptionTimingRequest(tmp_path / "a.mp4")
        )
    assert info.value.code == "provider_failure" and "/secret" not in info.value.message


def test_invalid_model_output_is_refused(fake_model, tmp_path):
    fake_model.segments = [FakeSegment([FakeWord(0.5, 9.0, " beyond", 0.9)])]  # audio is 2 s
    with pytest.raises(TimingOutputError):
        FasterWhisperWordTimingProvider(get_settings()).time_words(
            CaptionTimingRequest(tmp_path / "a.mp4")
        )


def test_decode_and_configuration_errors_are_mapped(monkeypatch, tmp_path):
    def missing(*args):
        raise ProviderConfigurationError(
            "faster-whisper is not installed in this environment", code="provider_missing"
        )

    monkeypatch.setattr(whisper_runtime, "_load_model", missing)
    with pytest.raises(TimingUnavailable) as info:
        FasterWhisperWordTimingProvider(get_settings()).time_words(
            CaptionTimingRequest(tmp_path / "a.mp4")
        )
    assert info.value.code == "provider_missing"

    monkeypatch.setattr(whisper_runtime, "_load_model", lambda *a: object())

    def bad_audio(path, ffmpeg_path):
        raise TranscriptionProviderError("audio_decode_failed", "The audio could not be decoded")

    monkeypatch.setattr(whisper_runtime, "_decode_pcm", bad_audio)
    with pytest.raises(CaptionTimingError) as info:
        FasterWhisperWordTimingProvider(get_settings()).time_words(
            CaptionTimingRequest(tmp_path / "a.mp4")
        )
    assert info.value.code == "audio_decode_failed"


# --- real model (opt-in: needs the "tiny" model and macOS `say`) -----


@pytest.mark.skipif(
    not os.environ.get("PEAKSIFT_REAL_WHISPER") or shutil.which("say") is None,
    reason="set PEAKSIFT_REAL_WHISPER=1 on macOS to run the real word-timing check",
)
def test_real_tiny_model_returns_ordered_word_timestamps(tmp_path, monkeypatch):
    aiff = tmp_path / "speech.aiff"
    subprocess.run(
        ["say", "-o", str(aiff), "One two three. Captions follow every word."], check=True
    )
    monkeypatch.setattr(whisper_runtime, "_MODEL_CACHE", {})
    provider = FasterWhisperWordTimingProvider(settings(faster_whisper_model="tiny"))
    result = provider.time_words(CaptionTimingRequest(aiff))
    texts = [x.text.lower().strip(".,") for x in result.words]
    assert result.language == "en" and len(result.words) >= 5, texts
    assert any(t in ("one", "1") for t in texts) and "captions" in texts
    assert all(a.end <= b.start for a, b in zip(result.words, result.words[1:], strict=False))
    assert result.words[-1].end <= result.audio_duration
