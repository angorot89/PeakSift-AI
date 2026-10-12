"""Local speech-to-text with faster-whisper (CTranslate2).

The model is loaded lazily on first use and cached per process, so importing this module
— or starting FastAPI / the Celery app — never downloads or loads a model. Only a worker
that actually transcribes pays that cost, once.

Audio is decoded to 16 kHz mono float32 PCM with ffmpeg and handed to the model as an
array. This bypasses faster-whisper's bundled PyAV decoder, which is incompatible with
the PyAV release available for this environment, and keeps every media subprocess on the
same argument-list + timeout rules as the rest of the backend.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import Settings
from app.services.transcription.contract import (
    ProviderCapabilities,
    ProviderConfigurationError,
    ProviderSegment,
    ProviderTranscriptionResult,
    TranscriptionProviderError,
    TranscriptionRequest,
    join_segment_text,
    validate_segments,
)

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # what Whisper models expect
DECODE_TIMEOUT_SECONDS = 600

CAPABILITIES = ProviderCapabilities(
    supports_segment_timestamps=True,
    supports_word_timestamps=True,  # available in faster-whisper; not requested in V0.3
    supports_language_detection=True,
    supports_diarization=False,
)

# (model, device, compute_type) -> loaded WhisperModel, shared by every provider instance
# in this worker process so a 4-hour stream's chunks reuse one model.
_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


def _load_model(model: str, device: str, compute_type: str) -> Any:
    key = (model, device, compute_type)
    if key not in _MODEL_CACHE:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise ProviderConfigurationError(
                "faster-whisper is not installed in this environment", code="provider_missing"
            ) from error
        logger.info("Loading faster-whisper model %s (%s, %s)", model, device, compute_type)
        try:
            _MODEL_CACHE[key] = WhisperModel(model, device=device, compute_type=compute_type)
        except Exception as error:
            # The exception text can contain cache paths; keep only its type.
            raise ProviderConfigurationError(
                f"faster-whisper model '{model}' could not be loaded "
                f"({type(error).__name__}); check FASTER_WHISPER_* settings",
                code="model_load_failed",
            ) from error
    return _MODEL_CACHE[key]


def _decode_pcm(path: Path, ffmpeg_path: str) -> np.ndarray:
    """Decode any audio file to 16 kHz mono float32 samples with ffmpeg."""
    if not path.is_file():
        raise TranscriptionProviderError("audio_missing", "The audio file to transcribe is missing")
    command = [
        ffmpeg_path,
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "-",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=DECODE_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError:
        raise ProviderConfigurationError(
            "ffmpeg is not installed on the server", code="ffmpeg_missing"
        ) from None
    except subprocess.TimeoutExpired:
        raise TranscriptionProviderError(
            "audio_decode_timeout", "Decoding the audio for transcription timed out"
        ) from None
    if result.returncode != 0:
        logger.warning("ffmpeg decode failed (exit %s)", result.returncode)
        raise TranscriptionProviderError(
            "audio_decode_failed",
            f"The audio could not be decoded (ffmpeg exit {result.returncode})",
        )
    return np.frombuffer(result.stdout, dtype=np.float32)


class FasterWhisperProvider:
    name = "faster_whisper"
    capabilities = CAPABILITIES

    def __init__(self, settings: Settings) -> None:
        self.model = settings.faster_whisper_model
        self._device = settings.faster_whisper_device
        self._compute_type = settings.faster_whisper_compute_type
        self._beam_size = settings.faster_whisper_beam_size
        self._ffmpeg_path = settings.ffmpeg_path

    def transcribe(self, request: TranscriptionRequest) -> ProviderTranscriptionResult:
        model = _load_model(self.model, self._device, self._compute_type)
        samples = _decode_pcm(request.audio_path, self._ffmpeg_path)
        try:
            raw_segments, info = model.transcribe(
                samples,
                beam_size=self._beam_size,
                language=request.language_hint,
                initial_prompt=request.prompt,
            )
            # The generator runs the model; consume it fully before returning.
            segments = validate_segments(
                ProviderSegment(start=float(s.start), end=float(s.end), text=s.text)
                for s in raw_segments
            )
        except TranscriptionProviderError:
            raise
        except Exception as error:
            logger.exception("faster-whisper failed on %s", request.audio_path.name)
            raise TranscriptionProviderError(
                "provider_failure", f"faster-whisper failed ({type(error).__name__})"
            ) from error

        return ProviderTranscriptionResult(
            text=join_segment_text(segments),
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            provider=self.name,
            model=self.model,
            segments=segments,
        )
