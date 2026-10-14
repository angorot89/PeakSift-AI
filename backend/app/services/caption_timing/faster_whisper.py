"""Local word timing with faster-whisper (``word_timestamps=True``).

Runs on the clip's own audio. It shares the transcription module's runtime — the lazily
loaded, per-process model cache and the ffmpeg PCM decoder — so a worker that both
transcribes and times captions loads one model, and nothing is loaded at import or startup.
faster-whisper 1.2 returns segments whose ``words`` are ``Word(start, end, word,
probability)``; they never leave this module.
"""

import logging

from app.core.config import Settings
from app.services.caption_timing.contract import (
    CaptionTimingError,
    CaptionTimingRequest,
    CaptionTimingResult,
    TimedWord,
    TimingCapabilities,
    TimingUnavailable,
    validate_words,
)
from app.services.transcription import faster_whisper as whisper_runtime
from app.services.transcription.contract import (
    ProviderConfigurationError,
    TranscriptionProviderError,
)

logger = logging.getLogger(__name__)

CAPABILITIES = TimingCapabilities(word_timestamps=True, language_detection=True, confidence=True)


class FasterWhisperWordTimingProvider:
    name = "faster_whisper"
    capabilities = CAPABILITIES

    def __init__(self, settings: Settings) -> None:
        self.model = settings.faster_whisper_model
        self._device = settings.faster_whisper_device
        self._compute_type = settings.faster_whisper_compute_type
        self._beam_size = settings.faster_whisper_beam_size
        self._ffmpeg_path = settings.ffmpeg_path
        self._tolerance = settings.caption_timing_tolerance_seconds

    def time_words(self, request: CaptionTimingRequest) -> CaptionTimingResult:
        try:
            model = whisper_runtime._load_model(self.model, self._device, self._compute_type)
            samples = whisper_runtime._decode_pcm(request.audio_path, self._ffmpeg_path)
        except ProviderConfigurationError as error:
            raise TimingUnavailable(error.code, error.message) from None
        except TranscriptionProviderError as error:
            raise CaptionTimingError(error.code, error.message) from None
        duration = len(samples) / whisper_runtime.SAMPLE_RATE
        if duration == 0:
            return CaptionTimingResult(self.name, self.model, None, None, 0.0, (), 0)
        try:
            segments, info = model.transcribe(
                samples,
                beam_size=self._beam_size,
                language=request.language_hint,
                word_timestamps=True,
            )
            raw = [
                TimedWord(float(w.start), float(w.end), str(w.word), w.probability)
                for segment in segments  # the generator runs the model
                for w in (segment.words or ())
            ]
        except Exception as error:
            logger.exception("faster-whisper word timing failed on %s", request.audio_path.name)
            raise CaptionTimingError(
                "provider_failure", f"Word timing failed ({type(error).__name__})"
            ) from None
        words, rejected = validate_words(raw, audio_duration=duration, tolerance=self._tolerance)
        probability = getattr(info, "language_probability", None)
        return CaptionTimingResult(
            provider=self.name,
            model=self.model,
            language=getattr(info, "language", None),
            language_probability=float(probability) if probability is not None else None,
            audio_duration=round(duration, 3),
            words=words,
            rejected_words=rejected,
        )
