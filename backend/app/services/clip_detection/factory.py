"""Choose a clip-analysis provider and model from what the server operator allows.

Unlike speech-to-text, the *user* picks a provider and model for clip detection — but
only from the allow-lists in server configuration. Endpoints (Ollama base URL) and
credentials (OpenAI key) are never chosen by clients.
"""

import importlib
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.services.clip_detection.contract import (
    ClipAnalysisProvider,
    ClipProviderConfigurationError,
)

# name -> "module:attribute". Imported lazily so the API never loads provider SDKs.
PROVIDER_REGISTRY: dict[str, str] = {
    "ollama": "app.services.clip_detection.ollama_provider:OllamaClipProvider",
    "openai": "app.services.clip_detection.openai_provider:OpenAIClipProvider",
}

PROVIDER_LABELS = {"ollama": "Local (Ollama)", "openai": "OpenAI"}


@dataclass(frozen=True)
class ProviderOption:
    """What a client may choose: a provider, its allowed models and whether it is configured."""

    name: str
    label: str
    models: tuple[str, ...]
    default_model: str | None
    configured: bool
    # Why the provider cannot be used, when it cannot. Safe for end users; never a URL or key.
    reason: str | None


def _split_models(value: str) -> tuple[str, ...]:
    seen: list[str] = []
    for item in value.split(","):
        model = item.strip()
        if model and model not in seen:
            seen.append(model)
    return tuple(seen)


def provider_options(settings: Settings | None = None) -> list[ProviderOption]:
    """Every known provider, in display order, with its configuration state."""
    settings = settings or get_settings()
    options: list[ProviderOption] = []

    ollama_models = _split_models(settings.ollama_clip_models)
    if not settings.clip_detection_ollama_enabled:
        reason: str | None = "The local provider is disabled on this server"
    elif not ollama_models:
        reason = "No local models are allowed on this server"
    else:
        reason = None
    options.append(
        ProviderOption(
            name="ollama",
            label=PROVIDER_LABELS["ollama"],
            models=ollama_models if reason is None else (),
            default_model=ollama_models[0] if reason is None else None,
            configured=reason is None,
            reason=reason,
        )
    )

    openai_models = _split_models(settings.openai_clip_models)
    has_key = bool(settings.openai_api_key and settings.openai_api_key.get_secret_value())
    if not has_key:
        reason = "OpenAI is not configured on this server"
    elif not openai_models:
        reason = "No OpenAI models are allowed on this server"
    else:
        reason = None
    options.append(
        ProviderOption(
            name="openai",
            label=PROVIDER_LABELS["openai"],
            models=openai_models if reason is None else (),
            default_model=openai_models[0] if reason is None else None,
            configured=reason is None,
            reason=reason,
        )
    )
    return options


def resolve_choice(
    provider: str, model: str | None, settings: Settings | None = None
) -> tuple[str, str]:
    """Validate a client's (provider, model) against the allow-lists; return the pair to use."""
    settings = settings or get_settings()
    option = next((o for o in provider_options(settings) if o.name == provider), None)
    if option is None:
        supported = ", ".join(sorted(PROVIDER_REGISTRY))
        raise ClipProviderConfigurationError(
            f"Unknown provider '{provider}'. Supported: {supported}", code="unknown_provider"
        )
    if not option.configured:
        raise ClipProviderConfigurationError(option.reason or "Provider unavailable")
    chosen = model or option.default_model
    if chosen not in option.models:
        raise ClipProviderConfigurationError(
            f"Model is not allowed for provider '{provider}'", code="model_not_allowed"
        )
    return provider, chosen


def get_clip_provider(
    provider: str, model: str | None = None, settings: Settings | None = None
) -> ClipAnalysisProvider:
    """Build the provider for an allowed (provider, model) pair. SDKs are imported lazily."""
    settings = settings or get_settings()
    name, chosen = resolve_choice(provider, model, settings)
    module_name, attribute = PROVIDER_REGISTRY[name].split(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise ClipProviderConfigurationError(
            f"Clip provider '{name}' is not available: {error.name or error}"
        ) from error
    instance: ClipAnalysisProvider = getattr(module, attribute)(settings, chosen)
    return instance
