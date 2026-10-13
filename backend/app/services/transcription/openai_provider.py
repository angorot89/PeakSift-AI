"""Hosted speech-to-text with the official OpenAI SDK.

Capability rule: PeakSift stores segment timestamps that later cut clips, so the
pipeline uses the configured *timestamp-capable* model (``OPENAI_TIMESTAMP_MODEL``,
``whisper-1``) with ``response_format="verbose_json"`` and segment granularity. Per the
installed SDK, ``gpt-4o-transcribe`` and ``gpt-4o-mini-transcribe`` return only ``json``
text, so they cannot fulfil the timestamp contract; configuring one of them as the
timestamp model is a capability error — timestamps are never fabricated.
"""

import logging
from typing import Any

import openai

from app.core.config import Settings
from app.services.transcription.contract import (
    ProviderCapabilities,
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderOutputError,
    ProviderSegment,
    ProviderTranscriptionResult,
    TranscriptionProviderError,
    TranscriptionRequest,
    join_segment_text,
    validate_segments,
)

logger = logging.getLogger(__name__)

# Models the installed SDK documents as supporting verbose_json segment timestamps.
TIMESTAMP_CAPABLE_MODELS = frozenset({"whisper-1"})

CAPABILITIES = ProviderCapabilities(
    supports_segment_timestamps=True,
    supports_word_timestamps=True,  # whisper-1 offers word granularity; not requested here
    supports_language_detection=True,
    supports_diarization=False,
)


class OpenAITranscriptionProvider:
    name = "openai"
    capabilities = CAPABILITIES

    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value():
            raise ProviderConfigurationError(
                "OPENAI_API_KEY is required when TRANSCRIPTION_PROVIDER=openai",
                code="missing_api_key",
            )
        self.model = settings.openai_timestamp_model
        if self.model not in TIMESTAMP_CAPABLE_MODELS:
            raise ProviderCapabilityError(
                f"OPENAI_TIMESTAMP_MODEL '{self.model}' does not return segment timestamps; "
                f"use one of: {', '.join(sorted(TIMESTAMP_CAPABLE_MODELS))}. "
                "PeakSift never fabricates timestamps."
            )
        self._max_upload_bytes = settings.openai_max_upload_bytes
        # Our pipeline applies bounded retries; keep the SDK's own retries minimal.
        self._client = openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=1,
        )

    def transcribe(self, request: TranscriptionRequest) -> ProviderTranscriptionResult:
        path = request.audio_path
        if not path.is_file():
            raise TranscriptionProviderError(
                "audio_missing", "The audio file to transcribe is missing"
            )
        size = path.stat().st_size
        if size > self._max_upload_bytes:
            raise TranscriptionProviderError(
                "audio_too_large",
                f"Audio chunk is {size // (1024 * 1024)} MB, above the hosted upload limit",
            )

        params: dict[str, Any] = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
        }
        if request.language_hint:
            params["language"] = request.language_hint
        if request.prompt:
            params["prompt"] = request.prompt

        try:
            with path.open("rb") as audio:
                response = self._client.audio.transcriptions.create(file=audio, **params)
        except openai.AuthenticationError as error:
            raise ProviderConfigurationError(
                "OpenAI rejected the API key", code="openai_authentication"
            ) from error
        except openai.PermissionDeniedError as error:
            raise ProviderConfigurationError(
                "OpenAI denied access to the transcription model", code="openai_permission"
            ) from error
        except openai.RateLimitError as error:
            raise TranscriptionProviderError(
                "openai_rate_limited", "OpenAI rate limit reached", retryable=True
            ) from error
        except (openai.APITimeoutError, openai.APIConnectionError) as error:
            raise TranscriptionProviderError(
                "openai_unreachable", "Could not reach OpenAI", retryable=True
            ) from error
        except openai.InternalServerError as error:
            raise TranscriptionProviderError(
                "openai_server_error", "OpenAI returned a server error", retryable=True
            ) from error
        except openai.APIStatusError as error:
            raise TranscriptionProviderError(
                "openai_request_rejected",
                f"OpenAI rejected the request (HTTP {error.status_code})",
            ) from error
        except openai.OpenAIError as error:
            # Type only: an SDK error message could echo request details (even the key).
            logger.warning("OpenAI SDK error (%s)", type(error).__name__)
            raise TranscriptionProviderError(
                "openai_error", f"OpenAI request failed ({type(error).__name__})"
            ) from error

        return self._normalise(response)

    def _normalise(self, response: Any) -> ProviderTranscriptionResult:
        raw_segments = getattr(response, "segments", None)
        if raw_segments is None:
            raise ProviderOutputError(
                "OpenAI returned no segment timestamps; the response cannot be used for clip timing"
            )
        try:
            segments = validate_segments(
                ProviderSegment(start=float(s.start), end=float(s.end), text=str(s.text))
                for s in raw_segments
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ProviderOutputError("OpenAI returned malformed segments") from error

        text = getattr(response, "text", None)
        return ProviderTranscriptionResult(
            text=(text or "").strip() or join_segment_text(segments),
            language=getattr(response, "language", None) or None,
            language_probability=None,  # not reported by the OpenAI API
            provider=self.name,
            model=self.model,
            segments=segments,
        )
