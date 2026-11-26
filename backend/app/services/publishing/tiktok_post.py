"""A TikTok post as the creator reviewed it: what they may choose, and checking their choices.

TikTok decides, per creator and at that moment, which visibility levels exist and whether
comments, duets and stitches can be offered (``creator_info``). PeakSift shows exactly those,
defaults nothing that TikTok requires the creator to choose, and checks the answer again on
the server — an invalid choice is refused with the field it belongs to, never repaired.

The rules come from TikTok's content sharing guidelines: visibility has no default; comment,
duet and stitch are off unless the creator turns them on; a commercial content disclosure
needs "your brand", "branded content" or both; branded content cannot be private; the creator
confirms TikTok's music usage terms; the video must fit the creator's maximum duration.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Privacy, PublishingConnection
from app.services.publishing import connections
from app.services.publishing.factory import get_publishing_provider
from app.services.publishing.metadata import (
    DESCRIPTION_MAX_BYTES,
    MetadataError,
    PublishMetadata,
)
from app.services.publishing.tiktok import CAPTION_MAX_UTF16, CreatorInfo
from app.services.publishing.tokens import TokenCipher

PRIVACY = {
    "SELF_ONLY": Privacy.PRIVATE,
    "PUBLIC_TO_EVERYONE": Privacy.PUBLIC,
    "FOLLOWER_OF_CREATOR": Privacy.FOLLOWERS,
    "MUTUAL_FOLLOW_FRIENDS": Privacy.FRIENDS,
}
_SWITCHES = ("allow_comment", "allow_duet", "allow_stitch")
_DISABLED = {
    "allow_comment": "comment_disabled",
    "allow_duet": "duet_disabled",
    "allow_stitch": "stitch_disabled",
}
_WORD = {"allow_comment": "Comments", "allow_duet": "Duets", "allow_stitch": "Stitches"}


def creator_info(db: Session, settings: Settings, connection: PublishingConnection) -> CreatorInfo:
    """Ask TikTok what this creator may choose right now. The refresh token rotates on use, so
    the new one is stored before the access token is used. Raises ``PublishProviderError``."""
    cipher = TokenCipher.from_settings(settings)
    provider = get_publishing_provider(settings, connection.provider)
    auth = provider.authorize(connections.refresh_token_of(db, cipher, connection))
    if auth.rotated_refresh_token:
        connections.store_rotated_token(db, cipher, connection, auth.rotated_refresh_token)
    return provider.creator_info(auth)


def _flag(options: Mapping[str, Any], name: str) -> bool:
    value = options.get(name, False)
    if not isinstance(value, bool):
        raise MetadataError(name, "Choose yes or no")
    return value


def choices(
    options: Mapping[str, Any], info: CreatorInfo, duration_seconds: float | None
) -> dict[str, Any]:
    """The creator's TikTok choices, checked against what TikTok offers them. Returns the
    options stored with the job; raises :class:`MetadataError` naming the field."""
    level = options.get("privacy_level")
    if not level:
        raise MetadataError("privacy_level", "Choose who can see this post")
    if level not in PRIVACY or level not in info.privacy_levels:
        raise MetadataError(
            "privacy_level", "That visibility is not available for your TikTok account"
        )
    chosen: dict[str, Any] = {"privacy_level": level}
    for name in _SWITCHES:
        chosen[name] = _flag(options, name)
        if chosen[name] and getattr(info, _DISABLED[name]):
            raise MetadataError(name, f"{_WORD[name]} are turned off in your TikTok settings")
    organic, branded = _flag(options, "brand_organic"), _flag(options, "brand_content")
    if _flag(options, "commercial") and not (organic or branded):
        raise MetadataError("commercial", "Choose your brand, branded content or both")
    if branded and level == "SELF_ONLY":
        raise MetadataError("privacy_level", "Branded content cannot be visible only to you")
    chosen["brand_organic"], chosen["brand_content"] = organic, branded
    if options.get("music_usage_confirmed") is not True:
        raise MetadataError("music_usage_confirmed", "Confirm TikTok's music usage terms to post")
    chosen["music_usage_confirmed"] = True
    limit = info.max_duration_seconds
    if limit and duration_seconds and duration_seconds > limit:
        raise MetadataError(
            "duration", f"This Short is longer than the {limit} seconds TikTok allows you"
        )
    return chosen


def metadata(title: str, text: str, level: str) -> PublishMetadata:
    """The stored form of a TikTok post: the Short's own title as its label (never sent to
    TikTok), the caption the creator wrote, and the visibility in PeakSift's words."""
    text = text.strip()
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise MetadataError("description", "Remove control characters")
    if len(text.encode("utf-16-le")) // 2 > CAPTION_MAX_UTF16:
        raise MetadataError(
            "description", f"A TikTok caption is at most {CAPTION_MAX_UTF16} characters"
        )
    if len(text.encode()) > DESCRIPTION_MAX_BYTES:
        raise MetadataError("description", "The caption is too long to store")
    label = " ".join(title.split())[:100] or "TikTok post"
    return PublishMetadata(label, text, (), PRIVACY[level], False)
