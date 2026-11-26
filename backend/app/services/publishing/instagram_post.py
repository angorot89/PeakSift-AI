"""An Instagram Reel as the creator reviewed it, checked before anything is sent to Meta.

Instagram has no visibility choice through the API: a Reel on a professional account is
public. So a post stores ``privacy = public`` and the dialog says so plainly. The caption is
checked against Meta's limits (2200 characters, 30 hashtags, 20 mentions) and refused rather
than shortened; the Short must last between 3 seconds and 15 minutes.
"""

from app.models import Privacy
from app.services.publishing.instagram import CAPTION_MAX, MAX_HASHTAGS, MAX_MENTIONS
from app.services.publishing.metadata import DESCRIPTION_MAX_BYTES, MetadataError, PublishMetadata

MIN_SECONDS, MAX_SECONDS = 3, 15 * 60


def metadata(title: str, caption: str, duration_seconds: float | None) -> PublishMetadata:
    text = caption.strip()
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise MetadataError("description", "Remove control characters")
    if len(text) > CAPTION_MAX:
        raise MetadataError(
            "description", f"An Instagram caption is at most {CAPTION_MAX} characters"
        )
    words = text.split()
    if sum(1 for word in words if word.startswith("#")) > MAX_HASHTAGS:
        raise MetadataError("description", f"Instagram allows at most {MAX_HASHTAGS} hashtags")
    if sum(1 for word in words if word.startswith("@")) > MAX_MENTIONS:
        raise MetadataError("description", f"Instagram allows at most {MAX_MENTIONS} mentions")
    if len(text.encode()) > DESCRIPTION_MAX_BYTES:
        raise MetadataError("description", "The caption is too long to store")
    if duration_seconds is not None and not MIN_SECONDS <= duration_seconds <= MAX_SECONDS:
        raise MetadataError("duration", "Instagram Reels last between 3 seconds and 15 minutes")
    label = " ".join(title.split())[:100] or "Instagram Reel"
    return PublishMetadata(label, text, (), Privacy.PUBLIC, False)
