"""The configured publishing provider (``PUBLISHING_PROVIDER``)."""

from functools import cache

from app.core.config import Settings
from app.services.publishing.provider import PublishingProvider


@cache
def _fake():
    from app.services.publishing.fake import FakePublishingProvider

    # One per process: the simulated "YouTube" must remember uploads between tasks.
    return FakePublishingProvider()


def get_publishing_provider(settings: Settings) -> PublishingProvider:
    if settings.publishing_provider == "fake":
        if settings.is_production:  # also refused at startup; never simulate in production
            raise RuntimeError("the fake publishing provider is not available in production")
        return _fake()
    from app.services.publishing.youtube import YouTubeProvider

    return YouTubeProvider.from_settings(settings)
