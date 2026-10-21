"""Which embedding provider this server uses, created lazily and cached per process.

``configured_identity`` answers "which model's vectors count here?" from configuration alone
(no model is loaded), so the API can report each asset's state cheaply. ``get_provider``
builds the provider on first use and keeps it for the life of the process: one model copy per
worker or API process, never one per request. Models load only when something is actually
embedded (an indexing job, or a search query's text), never at import or startup.
"""

import threading

from app.core.config import Settings
from app.services.semantic.contract import EmbeddingUnavailable, VisualEmbeddingProvider
from app.services.semantic.state import EmbeddingIdentity

_lock = threading.Lock()
_providers: dict[tuple[str, str], VisualEmbeddingProvider] = {}


def configured_identity(settings: Settings) -> EmbeddingIdentity | None:
    """The current embedding identity, or None when visual search is turned off."""
    if settings.semantic_provider == "clip_onnx":
        from app.services.semantic.clip_onnx import CLIP_IDENTITY

        return CLIP_IDENTITY
    if settings.semantic_provider == "fake":
        from app.services.semantic.fake import FAKE_IDENTITY

        return FAKE_IDENTITY
    return None


def get_provider(settings: Settings) -> VisualEmbeddingProvider:
    key = (settings.semantic_provider, settings.semantic_model_dir)
    with _lock:
        provider = _providers.get(key)
        if provider is None:
            provider = _build(settings)
            _providers[key] = provider
        return provider


def _build(settings: Settings) -> VisualEmbeddingProvider:
    if settings.semantic_provider == "clip_onnx":
        from app.services.semantic.clip_onnx import ClipOnnxProvider

        return ClipOnnxProvider.from_settings(settings)
    if settings.semantic_provider == "fake":
        from app.services.semantic.fake import FakeEmbeddingProvider

        return FakeEmbeddingProvider()
    raise EmbeddingUnavailable("Visual search is turned off on this server")


def install_provider(settings: Settings, provider: VisualEmbeddingProvider) -> None:
    """Use ``provider`` for this configuration (tests and benchmarks)."""
    with _lock:
        _providers[(settings.semantic_provider, settings.semantic_model_dir)] = provider


def reset_providers() -> None:
    with _lock:
        _providers.clear()
