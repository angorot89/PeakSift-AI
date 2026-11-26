"""The platforms PeakSift can publish to, in one place.

A platform is what the creator sees and connects ("YouTube", "TikTok"); its key is what a
connection, an OAuth state and a publish job record in their ``provider`` column. Everything
that differs between platforms hangs off this registry — whether this server offers it, what
it calls an account — so adding one is: a provider (``provider.py``'s contract), its OAuth,
an entry here and its key in ``PublishingProvider``.

Only platforms with a working provider are listed. Nothing here is a promise of a platform
that does not exist yet.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import Settings
from app.models import PublishingProvider


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    account_noun: str  # what the creator connects: a "channel", an "account"
    # Whether this server is set up to publish there (credentials present and switched on).
    enabled: Callable[[Settings], bool]


PLATFORMS: tuple[Platform, ...] = (
    Platform(
        key=PublishingProvider.YOUTUBE.value,
        label="YouTube",
        account_noun="channel",
        enabled=lambda settings: settings.youtube_publishing_enabled,
    ),
    Platform(
        key=PublishingProvider.TIKTOK.value,
        label="TikTok",
        account_noun="account",
        enabled=lambda settings: settings.tiktok_publishing_enabled,
    ),
    Platform(
        key=PublishingProvider.INSTAGRAM.value,
        label="Instagram",
        account_noun="account",
        enabled=lambda settings: settings.instagram_publishing_enabled,
    ),
)


def get(key: str) -> Platform | None:
    return next((platform for platform in PLATFORMS if platform.key == key), None)


def label(key: str) -> str:
    """The platform's name for messages; an unknown key reads as itself, capitalised."""
    platform = get(key)
    return platform.label if platform else key.capitalize()
