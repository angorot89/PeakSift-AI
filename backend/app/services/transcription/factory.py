"""Build the configured provider. Provider choice is server configuration, never client input."""

import importlib

from app.core.config import Settings, get_settings
from app.services.transcription.contract import (
    ProviderConfigurationError,
    TranscriptionProvider,
    require_segment_timestamps,
)

# name -> "module:attribute". Imported lazily so the API never loads provider SDKs.
PROVIDER_REGISTRY: dict[str, str] = {
    "faster_whisper": "app.services.transcription.faster_whisper:FasterWhisperProvider",
    "openai": "app.services.transcription.openai_provider:OpenAITranscriptionProvider",
}


def get_transcription_provider(settings: Settings | None = None) -> TranscriptionProvider:
    """The provider named by TRANSCRIPTION_PROVIDER, verified to meet the timestamp contract."""
    settings = settings or get_settings()
    name = settings.transcription_provider
    target = PROVIDER_REGISTRY.get(name)
    if target is None:
        supported = ", ".join(sorted(PROVIDER_REGISTRY))
        raise ProviderConfigurationError(
            f"Unsupported TRANSCRIPTION_PROVIDER '{name}'. Supported: {supported}"
        )

    module_name, attribute = target.split(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise ProviderConfigurationError(
            f"Transcription provider '{name}' is not available: {error.name or error}"
        ) from error
    provider: TranscriptionProvider = getattr(module, attribute)(settings)
    require_segment_timestamps(provider)
    return provider
