"""The configured caption-timing provider (server configuration, allow-listed)."""

from app.core.config import Settings
from app.services.caption_timing.contract import CaptionTimingProvider, TimingUnavailable


def get_timing_provider(settings: Settings) -> CaptionTimingProvider:
    """Construct the provider. Cheap: no model is loaded until words are timed."""
    if settings.caption_timing_provider == "faster_whisper":
        from app.services.caption_timing.faster_whisper import FasterWhisperWordTimingProvider

        return FasterWhisperWordTimingProvider(settings)
    raise TimingUnavailable(
        "provider_unknown", "The configured caption timing provider is not supported"
    )
