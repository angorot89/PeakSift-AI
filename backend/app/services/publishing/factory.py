"""The publishing provider for a platform (or the simulation, ``PUBLISHING_PROVIDER=fake``)."""

import secrets
from functools import cache

from app.core.config import Settings
from app.services.publishing.provider import PublishingProvider


@cache
def _fake():
    from app.services.publishing.fake import FakePublishingProvider

    # One per process: the simulated platform must remember uploads between tasks. Its video
    # ids carry a per-process prefix, so a restarted worker never repeats an earlier id.
    return FakePublishingProvider(id_prefix=secrets.token_hex(4))


def get_publishing_provider(settings: Settings, platform: str = "youtube") -> PublishingProvider:
    """The provider that talks to ``platform`` (a job's ``provider`` column)."""
    if settings.publishing_provider == "fake":
        if settings.is_production:  # also refused at startup; never simulate in production
            raise RuntimeError("the fake publishing provider is not available in production")
        return _fake()
    if platform == "youtube":
        from app.services.publishing.youtube import YouTubeProvider

        return YouTubeProvider.from_settings(settings)
    raise RuntimeError(f"no publishing provider for platform {platform!r}")
