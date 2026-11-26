"""The publishing provider contract (one implementation per platform).

The pipeline talks to a provider only through this module's types, so it never sees an SDK
object, an HTTP response or a provider error class:

- :meth:`PublishingProvider.authorize` turns the stored refresh token into a short-lived,
  opaque :class:`ProviderAuth` (never persisted);
- :meth:`start_upload` opens a **resumable upload session** for the video's metadata and
  returns its URI — a bearer secret the caller stores only encrypted;
- :meth:`upload_chunk` sends bytes at an offset and reports how many the provider has
  *confirmed*; :meth:`query_upload` asks for that count after an interruption, so an upload
  resumes where the provider says it stopped and the video is never created twice;
- :meth:`video_status` reports upload and processing state for the finished video.

Every failure is a :class:`PublishProviderError` with one of the normalized
:class:`PublishErrorCode` values, a message safe to show the user, and whether retrying
can help.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class PublishErrorCode(StrEnum):
    AUTHENTICATION_REQUIRED = "authentication_required"  # reconnect the account
    PERMISSION_DENIED = "permission_denied"  # the account may not upload (e.g. no channel)
    QUOTA_EXCEEDED = "quota_exceeded"  # the provider's daily quota is spent
    RATE_LIMITED = "rate_limited"  # too many requests right now
    INVALID_METADATA = "invalid_metadata"  # the provider rejected title/description/tags/...
    UPLOAD_SESSION_EXPIRED = "upload_session_expired"  # the resumable session is gone
    NETWORK_ERROR = "network_error"  # the provider could not be reached
    PROVIDER_ERROR = "provider_error"  # the provider failed (5xx, unexpected answer)
    PROCESSING_FAILED = "processing_failed"  # uploaded, but the provider could not process it


RETRYABLE = frozenset(
    {PublishErrorCode.RATE_LIMITED, PublishErrorCode.NETWORK_ERROR, PublishErrorCode.PROVIDER_ERROR,
     PublishErrorCode.UPLOAD_SESSION_EXPIRED}
)  # fmt: skip

# Safe to show the creator; ``{platform}`` is the platform's own name ("YouTube", "TikTok").
USER_MESSAGES = {
    PublishErrorCode.AUTHENTICATION_REQUIRED: "{platform} needs you to reconnect your account",
    PublishErrorCode.PERMISSION_DENIED: "This {platform} account cannot publish videos",
    PublishErrorCode.QUOTA_EXCEEDED: "{platform}'s upload quota is used up for today; try tomorrow",
    PublishErrorCode.RATE_LIMITED: "{platform} asked us to slow down; try again in a few minutes",
    PublishErrorCode.INVALID_METADATA: "{platform} rejected the title, description or tags",
    PublishErrorCode.UPLOAD_SESSION_EXPIRED: "The upload session expired; retry to start again",
    PublishErrorCode.NETWORK_ERROR: "{platform} could not be reached; try again",
    PublishErrorCode.PROVIDER_ERROR: "{platform} had a problem; try again",
    PublishErrorCode.PROCESSING_FAILED: "{platform} could not process this video",
}
# Wording a platform needs beyond the general message.
PLATFORM_MESSAGES = {
    ("YouTube", PublishErrorCode.PERMISSION_DENIED): (
        "This YouTube account cannot upload videos (it may need a channel)"
    ),
}


def user_message(code: PublishErrorCode, platform: str = "YouTube") -> str:
    code = PublishErrorCode(code)
    return PLATFORM_MESSAGES.get((platform, code)) or USER_MESSAGES[code].format(platform=platform)


class PublishProviderError(Exception):
    def __init__(
        self, code: PublishErrorCode, message: str | None = None, *, platform: str = "YouTube"
    ) -> None:
        self.code = PublishErrorCode(code)
        self.message = message or user_message(self.code, platform)
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE


@dataclass(frozen=True)
class ProviderAuth:
    """A short-lived credential for one job. Opaque to callers; never stored or logged."""

    access_token: str = field(repr=False)
    # Set when the platform replaced the refresh token while authorizing (rotation): the caller
    # stores it, encrypted, before using the access token. Never logged.
    rotated_refresh_token: str | None = field(default=None, repr=False)
    # The platform account this credential acts for, when calls must name it (Instagram's
    # professional account id). Not a secret.
    account_id: str | None = None


@dataclass(frozen=True)
class VideoRequest:
    title: str
    description: str
    tags: tuple[str, ...]
    privacy: str
    made_for_kids: bool
    category_id: str
    size_bytes: int
    content_type: str = "video/mp4"
    # What the creator chose that only this platform has (e.g. TikTok's visibility level and
    # interaction switches). Validated values only; a provider ignores what it does not know.
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UploadProgress:
    confirmed_bytes: int  # bytes the provider has stored; the next chunk starts here
    video_id: str | None = None  # set once the upload is complete
    channel_id: str | None = None
    channel_title: str | None = None

    @property
    def complete(self) -> bool:
        return self.video_id is not None


class UploadState(StrEnum):
    UPLOADED = "uploaded"  # received; processing has not finished
    PROCESSED = "processed"  # ready to watch at its privacy
    FAILED = "failed"  # processing failed
    REJECTED = "rejected"  # e.g. duplicate, copyright or terms-of-use rejection
    DELETED = "deleted"
    # The granted scope does not let the provider report processing (YouTube's upload-only
    # scope cannot read videos): the honest end state is "uploaded".
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VideoStatus:
    upload: UploadState
    privacy: str | None = None
    reason: str | None = None  # the provider's short reason code, when it gave one


class PublishingProvider(Protocol):
    name: str

    def authorize(self, refresh_token: str) -> ProviderAuth: ...

    def start_upload(self, auth: ProviderAuth, request: VideoRequest) -> str: ...

    def query_upload(self, auth: ProviderAuth, session_uri: str, total: int) -> UploadProgress: ...

    def upload_chunk(
        self, auth: ProviderAuth, session_uri: str, data: bytes, offset: int, total: int
    ) -> UploadProgress: ...

    def video_status(self, auth: ProviderAuth, video_id: str) -> VideoStatus: ...

    # Optional: ``chunk_length(session_uri, offset, total) -> int``. A platform whose chunks
    # must follow a plan declared when the session was opened (TikTok) says how long the next
    # request must be; without it the uploader sends its configured chunk size.
