"""The publishing provider contract (YouTube is the only implementation).

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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


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

USER_MESSAGES = {
    PublishErrorCode.AUTHENTICATION_REQUIRED: "YouTube needs you to reconnect your account",
    PublishErrorCode.PERMISSION_DENIED: (
        "This YouTube account cannot upload videos (it may need a channel)"
    ),
    PublishErrorCode.QUOTA_EXCEEDED: "YouTube's upload quota is used up for today; try tomorrow",
    PublishErrorCode.RATE_LIMITED: "YouTube asked us to slow down; try again in a few minutes",
    PublishErrorCode.INVALID_METADATA: "YouTube rejected the title, description or tags",
    PublishErrorCode.UPLOAD_SESSION_EXPIRED: "The upload session expired; retry to start again",
    PublishErrorCode.NETWORK_ERROR: "YouTube could not be reached; try again",
    PublishErrorCode.PROVIDER_ERROR: "YouTube had a problem; try again",
    PublishErrorCode.PROCESSING_FAILED: "YouTube could not process this video",
}


class PublishProviderError(Exception):
    def __init__(self, code: PublishErrorCode, message: str | None = None) -> None:
        self.code = PublishErrorCode(code)
        self.message = message or USER_MESSAGES[self.code]
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE


@dataclass(frozen=True)
class ProviderAuth:
    """A short-lived credential for one job. Opaque to callers; never stored or logged."""

    access_token: str = field(repr=False)


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
