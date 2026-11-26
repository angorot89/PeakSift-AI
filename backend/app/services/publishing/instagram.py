"""Instagram Reels behind the publishing contract (Graph API v27.0, resumable upload).

How Meta's flow maps onto the contract:

- :meth:`authorize` opens the sealed connection value: the Page access token, and the
  Instagram professional account's id (``ProviderAuth.account_id``). No network call.
- :meth:`start_upload` creates a Reels container with ``upload_type=resumable``. Meta answers
  with the container id and its ``rupload.facebook.com`` URI: together they are the session.
- :meth:`upload_chunk` sends the file to that URI. Meta documents only a single request from
  offset 0, so the whole file is one request (:meth:`chunk_length`). No post exists until
  ``media_publish``, so sending the file again after an interruption can never post twice.
- :meth:`video_status` reads the container. ``FINISHED`` means Meta has processed it: only then
  is ``media_publish`` called, once — a container already ``PUBLISHED`` is never published again.
  The post exists on Instagram only after that call succeeds.

The id PeakSift keeps is the container id, not the post's; no link is built from it.
Meta's messages, tokens and upload URIs never leave this module.
"""

import json
import logging
from dataclasses import dataclass

import httpx

from app.services.publishing.instagram_oauth import GRAPH, GRAPH_VERSION, unseal
from app.services.publishing.provider import (
    ProviderAuth,
    PublishErrorCode,
    PublishProviderError,
    UploadProgress,
    UploadState,
    VideoRequest,
    VideoStatus,
)

logger = logging.getLogger(__name__)

PLATFORM = "Instagram"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/"
MAX_BYTES = 300 * 1024 * 1024  # Meta: a Reel is at most 300 MB
CAPTION_MAX = 2200
MAX_HASHTAGS = 30
MAX_MENTIONS = 20
TIMEOUT = httpx.Timeout(120.0, connect=10.0)

_AUTH = {190, 102}
_PERMISSION = {10, 200, 3}
_RATE = {4, 17, 32, 613}
_LIMIT = {9}  # "application request limit reached": Instagram's daily publishing limit
_INVALID = {100, 25, 36003}


def classify(status: int, code: int | None, transient: bool = False) -> PublishErrorCode:
    """Meta's HTTP status and Graph error code → the contract's code."""
    if status == 401 or code in _AUTH:
        return PublishErrorCode.AUTHENTICATION_REQUIRED
    if code in _LIMIT:
        return PublishErrorCode.QUOTA_EXCEEDED
    if status == 429 or code in _RATE:
        return PublishErrorCode.RATE_LIMITED
    if transient or status >= 500:
        return PublishErrorCode.PROVIDER_ERROR
    if status == 403 or code in _PERMISSION:
        return PublishErrorCode.PERMISSION_DENIED
    if code in _INVALID or status == 400:
        return PublishErrorCode.INVALID_METADATA
    return PublishErrorCode.PROVIDER_ERROR


def check_caption(text: str) -> str:
    """A caption Instagram accepts, unchanged — or the reason it would not, never shortened."""
    text = text.strip()
    if len(text) > CAPTION_MAX:
        raise PublishProviderError(
            PublishErrorCode.INVALID_METADATA,
            f"An Instagram caption is at most {CAPTION_MAX} characters",
            platform=PLATFORM,
        )
    words = text.split()
    if sum(1 for word in words if word.startswith("#")) > MAX_HASHTAGS:
        raise PublishProviderError(
            PublishErrorCode.INVALID_METADATA,
            f"Instagram allows at most {MAX_HASHTAGS} hashtags",
            platform=PLATFORM,
        )
    if sum(1 for word in words if word.startswith("@")) > MAX_MENTIONS:
        raise PublishProviderError(
            PublishErrorCode.INVALID_METADATA,
            f"Instagram allows at most {MAX_MENTIONS} mentions",
            platform=PLATFORM,
        )
    return text


@dataclass(frozen=True)
class Session:
    container_id: str
    upload_uri: str

    def dump(self) -> str:
        return json.dumps({"c": self.container_id, "u": self.upload_uri})

    @classmethod
    def load(cls, raw: str) -> "Session":
        try:
            data = json.loads(raw)
            session = cls(str(data["c"]), str(data["u"]))
        except (ValueError, KeyError, TypeError):
            raise PublishProviderError(
                PublishErrorCode.UPLOAD_SESSION_EXPIRED, platform=PLATFORM
            ) from None
        if not session.upload_uri.startswith(RUPLOAD) or not session.container_id.isdigit():
            raise PublishProviderError(PublishErrorCode.UPLOAD_SESSION_EXPIRED, platform=PLATFORM)
        return session


class InstagramProvider:
    name = "instagram"
    # A post exists only after the server publishes the processed container (see check_status).
    publishes_after_processing = True

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT)

    # --- transport -------------------------------------------------------------------

    def _call(self, method: str, url: str, token: str, **kwargs) -> dict:
        headers = {"Authorization": f"OAuth {token}", **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise PublishProviderError(PublishErrorCode.NETWORK_ERROR, platform=PLATFORM) from None
        try:
            body = response.json()
        except ValueError:
            body = None
        error = body.get("error") if isinstance(body, dict) else None
        debug = body.get("debug_info") if isinstance(body, dict) else None
        if response.status_code >= 400 or isinstance(error, dict) or isinstance(debug, dict):
            detail = error if isinstance(error, dict) else {}
            code = detail.get("code") if isinstance(detail.get("code"), int) else None
            transient = bool(detail.get("is_transient")) or bool(
                isinstance(debug, dict) and debug.get("retriable")
            )
            logger.info("Instagram refused a request (%s, %s)", response.status_code, code)
            raise PublishProviderError(
                classify(response.status_code, code, transient), platform=PLATFORM
            )
        if not isinstance(body, dict):
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        return body

    # --- the contract ----------------------------------------------------------------

    def authorize(self, refresh_token: str) -> ProviderAuth:
        opened = unseal(refresh_token)
        if opened is None:
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED, platform=PLATFORM)
        token, account = opened
        return ProviderAuth(token, account_id=account)

    def start_upload(self, auth: ProviderAuth, request: VideoRequest) -> str:
        if request.size_bytes > MAX_BYTES:
            raise PublishProviderError(
                PublishErrorCode.INVALID_METADATA,
                "Instagram accepts Reels up to 300 MB",
                platform=PLATFORM,
            )
        caption = check_caption(request.description)
        body = self._call(
            "POST",
            f"{GRAPH}/{auth.account_id}/media",
            auth.access_token,
            data={"media_type": "REELS", "upload_type": "resumable", "caption": caption},
        )
        container, uri = str(body.get("id") or ""), str(body.get("uri") or "")
        if not container.isdigit():
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        if not uri.startswith(RUPLOAD):
            uri = f"{RUPLOAD}{container}"  # the documented form, when Meta did not repeat it
        return Session(container, uri).dump()

    def chunk_length(self, session_uri: str, offset: int, total: int) -> int:
        """Meta documents one request from offset 0: the whole file."""
        Session.load(session_uri)
        return total - offset

    def upload_chunk(
        self, auth: ProviderAuth, session_uri: str, data: bytes, offset: int, total: int
    ) -> UploadProgress:
        session = Session.load(session_uri)
        if offset != 0 or len(data) != total:
            # A partial upload cannot be resumed: send the whole file again (no post exists yet).
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        body = self._call(
            "POST",
            session.upload_uri,
            auth.access_token,
            content=data,
            headers={"offset": "0", "file_size": str(total)},
        )
        if body.get("success") is not True:
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        return UploadProgress(total, video_id=session.container_id)

    def _container(self, auth: ProviderAuth, container_id: str) -> tuple[str, str]:
        body = self._call(
            "GET",
            f"{GRAPH}/{container_id}",
            auth.access_token,
            params={"fields": "status_code,status"},
        )
        return str(body.get("status_code") or ""), str(body.get("status") or "")

    def query_upload(self, auth: ProviderAuth, session_uri: str, total: int) -> UploadProgress:
        session = Session.load(session_uri)
        state, _ = self._container(auth, session.container_id)
        if state in ("FINISHED", "PUBLISHED"):
            return UploadProgress(total, video_id=session.container_id)  # Meta has the file
        if state in ("ERROR", "EXPIRED"):
            raise PublishProviderError(PublishErrorCode.UPLOAD_SESSION_EXPIRED, platform=PLATFORM)
        return UploadProgress(0)  # no byte count is documented: the file goes again, whole

    def video_status(self, auth: ProviderAuth, video_id: str) -> VideoStatus:
        state, detail = self._container(auth, video_id)
        if state == "PUBLISHED":
            return VideoStatus(UploadState.PROCESSED)
        if state == "FINISHED":
            return self._publish(auth, video_id)
        if state == "ERROR":
            return VideoStatus(UploadState.FAILED, reason=(detail or "error")[:64])
        if state == "EXPIRED":
            return VideoStatus(UploadState.FAILED, reason="expired")
        return VideoStatus(UploadState.UPLOADED)  # IN_PROGRESS: Meta is still processing it

    def _publish(self, auth: ProviderAuth, container_id: str) -> VideoStatus:
        try:
            body = self._call(
                "POST",
                f"{GRAPH}/{auth.account_id}/media_publish",
                auth.access_token,
                data={"creation_id": container_id},
            )
        except PublishProviderError as error:
            # Two checks at once: the other one may have published it. Never publish twice.
            state, _ = self._container(auth, container_id)
            if state == "PUBLISHED":
                return VideoStatus(UploadState.PROCESSED)
            if error.retryable:
                return VideoStatus(UploadState.UPLOADED)  # try again at the next check
            raise
        if not str(body.get("id") or "").isdigit():
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR, platform=PLATFORM)
        return VideoStatus(UploadState.PROCESSED)
