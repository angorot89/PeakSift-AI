"""TikTok behind the publishing contract (Content Posting API, direct post, ``FILE_UPLOAD``).

How TikTok's flow maps onto the contract:

- :meth:`authorize` refreshes the access token. TikTok **rotates** refresh tokens, so the new
  one is returned in ``ProviderAuth.rotated_refresh_token`` for the pipeline to store first.
- :meth:`start_upload` calls ``/v2/post/publish/video/init/``. TikTok answers with a
  ``publish_id`` and an ``upload_url`` (valid for one hour). Both, with the chunk plan declared
  to TikTok, are the opaque *session* the pipeline stores encrypted.
- :meth:`upload_chunk` ``PUT``s bytes to the upload URL with ``Content-Range``; ``206`` means
  more is expected, ``201`` that TikTok has the whole file. Chunks must follow the declared
  plan, so the uploader asks :meth:`chunk_length` for each one.
- :meth:`query_upload` and :meth:`video_status` both read ``/v2/post/publish/status/fetch/``:
  TikTok reports the bytes it holds and then ``PUBLISH_COMPLETE`` or ``FAILED`` with a reason.
- The "video id" the pipeline keeps is TikTok's ``publish_id``. It is not a public video id —
  TikTok only reports one for public posts after moderation — so no link is ever built from it.

What the creator chose for this post travels in ``VideoRequest.options``: ``privacy_level``
(one of the levels TikTok offers *that* creator, see :meth:`creator_info`; never defaulted),
``allow_comment`` / ``allow_duet`` / ``allow_stitch`` (off unless chosen),
``brand_organic`` / ``brand_content`` (commercial content disclosure) and ``is_aigc``.

Errors become the contract's codes from the HTTP status and TikTok's error code. TikTok's
messages, upload URLs and tokens never leave this module.
"""

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.services.publishing.provider import (
    ProviderAuth,
    PublishErrorCode,
    PublishProviderError,
    UploadProgress,
    UploadState,
    VideoRequest,
    VideoStatus,
)
from app.services.publishing.tiktok_oauth import TOKEN_URL

logger = logging.getLogger(__name__)

API = "https://open.tiktokapis.com"
INIT_URL = f"{API}/v2/post/publish/video/init/"
STATUS_URL = f"{API}/v2/post/publish/status/fetch/"
CREATOR_URL = f"{API}/v2/post/publish/creator_info/query/"
PLATFORM = "TikTok"

MIN_CHUNK = 5 * 1024 * 1024  # TikTok: a chunk is at least 5 MB (the last may be larger)
MAX_CHUNK = 64_000_000  # … and at most 64 MB
MAX_CHUNKS = 1000
CAPTION_MAX_UTF16 = 2200
PRIVACY_LEVELS = frozenset(
    {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
)
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_RANGE = re.compile(r"^bytes \d+-(\d+)/\d+$")

_AUTH = {"access_token_invalid", "invalid_grant", "token_expired"}
_PERMISSION = {
    "scope_not_authorized",
    "unaudited_client_can_only_post_to_private_accounts",
    "reached_active_user_cap",
    "app_version_check_failed",
}
_QUOTA = {"spam_risk_too_many_posts", "spam_risk_too_many_pending_share"}
_REJECTED = {"spam_risk_user_banned_from_posting", "spam_risk_text", "spam_risk", "auth_removed"}
_METADATA = {
    "invalid_param",
    "invalid_params",
    "privacy_level_option_mismatch",
    "invalid_file_upload",
}

# What TikTok's own restriction means for the creator, in words they can act on.
MESSAGES = {
    "unaudited_client_can_only_post_to_private_accounts": (
        "TikTok only lets this app post to private accounts for now. Set your TikTok account "
        "to private, or wait until the app has passed TikTok's review"
    ),
    "reached_active_user_cap": (
        "TikTok limits how many people can post through this app each day until it has passed "
        "TikTok's review. Try again tomorrow"
    ),
    "spam_risk_too_many_posts": "TikTok's daily posting limit for this account is reached",
    "privacy_level_option_mismatch": (
        "That visibility is not available for your TikTok account. Choose another one"
    ),
}


def classify(status: int, code: str, *, upload: bool = False) -> PublishErrorCode:
    """TikTok's HTTP status and error code → the contract's code."""
    if status == 401 or code in _AUTH:
        return PublishErrorCode.AUTHENTICATION_REQUIRED
    if code in _QUOTA:
        return PublishErrorCode.QUOTA_EXCEEDED
    if status == 429 or code == "rate_limit_exceeded":
        return PublishErrorCode.RATE_LIMITED
    if upload and status in (403, 404):
        return PublishErrorCode.UPLOAD_SESSION_EXPIRED  # the upload URL expired or is unknown
    if status == 403 or code in _PERMISSION:
        return PublishErrorCode.PERMISSION_DENIED
    if code in _METADATA or (status == 400 and not upload):
        return PublishErrorCode.INVALID_METADATA
    return PublishErrorCode.PROVIDER_ERROR


def _error(status: int, code: str = "", *, upload: bool = False) -> PublishProviderError:
    return PublishProviderError(
        classify(status, code, upload=upload), MESSAGES.get(code), platform=PLATFORM
    )


def chunk_plan(size: int, preferred: int) -> tuple[int, int]:
    """``(chunk_size, total_chunk_count)`` as TikTok wants them declared.

    Every chunk but the last is exactly ``chunk_size``; the last one carries the remainder too
    (so it is between one and two chunks long). A file under 5 MB is one chunk.
    """
    if size <= 0:
        raise PublishProviderError(PublishErrorCode.INVALID_METADATA, platform=PLATFORM)
    if size < MIN_CHUNK:
        return size, 1
    chunk = min(max(preferred, MIN_CHUNK), MAX_CHUNK)
    if size // chunk > MAX_CHUNKS:
        chunk = min(-(-size // MAX_CHUNKS), MAX_CHUNK)
    return chunk, max(1, size // chunk)


@dataclass(frozen=True)
class Session:
    """The upload session as stored (encrypted) by the pipeline. Opaque outside this module."""

    publish_id: str
    upload_url: str
    chunk_size: int
    chunks: int

    def dump(self) -> str:
        return json.dumps(
            {"p": self.publish_id, "u": self.upload_url, "c": self.chunk_size, "n": self.chunks}
        )

    @classmethod
    def load(cls, raw: str) -> "Session":
        try:
            data = json.loads(raw)
            session = cls(str(data["p"]), str(data["u"]), int(data["c"]), int(data["n"]))
        except (ValueError, KeyError, TypeError):
            raise PublishProviderError(
                PublishErrorCode.UPLOAD_SESSION_EXPIRED, platform=PLATFORM
            ) from None
        if not session.upload_url.startswith("https://") or session.chunk_size <= 0:
            raise PublishProviderError(PublishErrorCode.UPLOAD_SESSION_EXPIRED, platform=PLATFORM)
        return session


@dataclass(frozen=True)
class CreatorInfo:
    """What TikTok says this creator may choose right now (shown in the publish dialog)."""

    nickname: str
    username: str
    privacy_levels: tuple[str, ...]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_duration_seconds: int | None


def caption(request: VideoRequest) -> str:
    """The post's caption: the description the creator reviewed, else the title."""
    text = (request.description or request.title).strip()
    if len(text.encode("utf-16-le")) // 2 > CAPTION_MAX_UTF16:
        raise PublishProviderError(
            PublishErrorCode.INVALID_METADATA,
            f"A TikTok caption is at most {CAPTION_MAX_UTF16} characters",
            platform=PLATFORM,
        )
    return text


class TikTokProvider:
    name = "tiktok"

    def __init__(
        self,
        client_key: str,
        client_secret: str,
        *,
        chunk_bytes: int = 10 * 1024 * 1024,
        client: httpx.Client | None = None,
    ) -> None:
        self._client_key = client_key
        self._client_secret = client_secret
        self._chunk_bytes = chunk_bytes
        self._client = client or httpx.Client(timeout=TIMEOUT)

    @classmethod
    def from_settings(cls, settings: Settings) -> "TikTokProvider":
        secret = settings.tiktok_client_secret
        return cls(
            settings.tiktok_client_key,
            secret.get_secret_value() if secret else "",
            chunk_bytes=settings.tiktok_upload_chunk_bytes,
        )

    # --- transport -------------------------------------------------------------------

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            return self._client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise PublishProviderError(PublishErrorCode.NETWORK_ERROR, platform=PLATFORM) from None

    def _api(self, auth: ProviderAuth, url: str, body: dict) -> dict:
        """One JSON call to the Content Posting API; returns its ``data`` object."""
        response = self._send(
            "POST",
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {auth.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        code = str(error.get("code") or "") if isinstance(error, dict) else ""
        if response.status_code >= 400 or (code and code != "ok"):
            logger.info("TikTok refused a request (%s, %s)", response.status_code, code or "-")
            raise _error(response.status_code, code)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        return data

    # --- the contract ----------------------------------------------------------------

    def authorize(self, refresh_token: str) -> ProviderAuth:
        response = self._send(
            "POST",
            TOKEN_URL,
            data={
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Cache-Control": "no-cache"},
        )
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 500:
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        if response.status_code >= 400 or not isinstance(body, dict) or body.get("error"):
            # The grant is gone (revoked, expired after 180 days, or already rotated away).
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED, platform=PLATFORM)
        access, rotated = body.get("access_token"), body.get("refresh_token")
        if not isinstance(access, str) or not access:
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        changed = isinstance(rotated, str) and rotated and rotated != refresh_token
        return ProviderAuth(access, rotated_refresh_token=rotated if changed else None)

    def creator_info(self, auth: ProviderAuth) -> CreatorInfo:
        data = self._api(auth, CREATOR_URL, {})
        levels = tuple(
            level for level in data.get("privacy_level_options") or () if level in PRIVACY_LEVELS
        )
        duration = data.get("max_video_post_duration_sec")
        return CreatorInfo(
            nickname=str(data.get("creator_nickname") or "")[:255],
            username=str(data.get("creator_username") or "")[:255],
            privacy_levels=levels,
            comment_disabled=bool(data.get("comment_disabled")),
            duet_disabled=bool(data.get("duet_disabled")),
            stitch_disabled=bool(data.get("stitch_disabled")),
            max_duration_seconds=duration if isinstance(duration, int) and duration > 0 else None,
        )

    def start_upload(self, auth: ProviderAuth, request: VideoRequest) -> str:
        options = request.options
        level = options.get("privacy_level")
        if level not in PRIVACY_LEVELS:  # the creator must have chosen one; never defaulted
            raise PublishProviderError(
                PublishErrorCode.INVALID_METADATA,
                "Choose who can see this TikTok post",
                platform=PLATFORM,
            )
        chunk, count = chunk_plan(request.size_bytes, self._chunk_bytes)
        data = self._api(
            auth,
            INIT_URL,
            {
                "post_info": {
                    "title": caption(request),
                    "privacy_level": level,
                    "disable_comment": not options.get("allow_comment", False),
                    "disable_duet": not options.get("allow_duet", False),
                    "disable_stitch": not options.get("allow_stitch", False),
                    "brand_organic_toggle": bool(options.get("brand_organic", False)),
                    "brand_content_toggle": bool(options.get("brand_content", False)),
                    "is_aigc": bool(options.get("is_aigc", False)),
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": request.size_bytes,
                    "chunk_size": chunk,
                    "total_chunk_count": count,
                },
            },
        )
        publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
        if not isinstance(publish_id, str) or not isinstance(upload_url, str):
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        return Session(publish_id, upload_url, chunk, count).dump()

    def chunk_length(self, session_uri: str, offset: int, total: int) -> int:
        """How many bytes the next request must carry, by the plan declared to TikTok."""
        session = Session.load(session_uri)
        if offset % session.chunk_size or offset >= total:
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        last = offset // session.chunk_size >= session.chunks - 1
        return total - offset if last else session.chunk_size

    def upload_chunk(
        self, auth: ProviderAuth, session_uri: str, data: bytes, offset: int, total: int
    ) -> UploadProgress:
        session = Session.load(session_uri)
        end = offset + len(data) - 1
        response = self._send(
            "PUT",
            session.upload_url,
            content=data,
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {offset}-{end}/{total}",
            },
        )
        if response.status_code == 201:
            return UploadProgress(total, video_id=session.publish_id)
        if response.status_code == 206:
            match = _RANGE.match(response.headers.get("Content-Range", ""))
            return UploadProgress(int(match.group(1)) + 1 if match else end + 1)
        if response.status_code == 416:
            # TikTok holds a different number of bytes than we assumed: ask and resume.
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        raise _error(response.status_code, upload=True)

    def _status(self, auth: ProviderAuth, publish_id: str) -> dict:
        return self._api(auth, STATUS_URL, {"publish_id": publish_id})

    def query_upload(self, auth: ProviderAuth, session_uri: str, total: int) -> UploadProgress:
        session = Session.load(session_uri)
        data = self._status(auth, session.publish_id)
        state = data.get("status")
        if state == "FAILED":
            raise self._failed(data)
        received = data.get("uploaded_bytes")
        received = received if isinstance(received, int) and received >= 0 else 0
        if state != "PROCESSING_UPLOAD" or received >= total:
            return UploadProgress(total, video_id=session.publish_id)  # TikTok has every byte
        # Only whole chunks count: the next request must start on a chunk boundary.
        return UploadProgress(received - received % session.chunk_size)

    def _failed(self, data: dict) -> PublishProviderError:
        reason = str(data.get("fail_reason") or "")
        if reason == "internal":
            return PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        if reason in _QUOTA:
            return _error(200, reason)
        return PublishProviderError(
            PublishErrorCode.PROCESSING_FAILED, MESSAGES.get(reason), platform=PLATFORM
        )

    def video_status(self, auth: ProviderAuth, video_id: str) -> VideoStatus:
        data = self._status(auth, video_id)
        state = data.get("status")
        if state == "PUBLISH_COMPLETE":
            return VideoStatus(UploadState.PROCESSED)
        if state == "FAILED":
            reason = str(data.get("fail_reason") or "")[:64] or None
            rejected = reason in _REJECTED
            return VideoStatus(
                UploadState.REJECTED if rejected else UploadState.FAILED, reason=reason
            )
        return VideoStatus(UploadState.UPLOADED)  # still being processed or moderated
