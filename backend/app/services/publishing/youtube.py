"""YouTube: resumable ``videos.insert`` over Google's documented upload protocol.

- **Authorization:** the official ``google-auth`` library exchanges the stored refresh token
  for an access token per job (never stored). ``invalid_grant`` — revoked or expired consent
  — becomes ``authentication_required``, so the connection is marked for reconnecting.
- **Session:** ``POST …/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status``
  with the metadata returns the session URI in ``Location``. The URI is a bearer secret:
  returned to the caller only to be stored encrypted.
- **Bytes:** ``PUT <session>`` with ``Content-Range: bytes a-b/total``. ``308 Resume
  Incomplete`` carries ``Range: bytes=0-N`` — what YouTube actually stored — and the next
  chunk starts at N+1; ``200/201`` returns the created video. ``PUT`` with
  ``Content-Range: bytes */total`` asks where an interrupted upload stands, so a restarted
  worker resumes instead of creating a second video. Chunks are multiples of 256 KiB, as
  Google requires (except the last).
- **Processing:** ``videos.list`` needs a read scope this integration does not request; when
  YouTube refuses it for that reason the status is ``unknown`` and the pipeline stops at an
  honest "uploaded".
- **Errors** become the contract's normalized codes from the HTTP status and Google's
  ``reason``. Google's messages, session URIs and tokens never leave this module.
"""

import json
import logging
import re
from collections.abc import Callable

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
from app.services.publishing.youtube_oauth import TOKEN_URI, UPLOAD_SCOPE

logger = logging.getLogger(__name__)

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHUNK_MULTIPLE = 256 * 1024
_RANGE = re.compile(r"^bytes=0-(\d+)$")

_QUOTA = {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"}
_RATE = {"rateLimitExceeded", "userRateLimitExceeded"}
_PERMISSION = {"forbidden", "insufficientPermissions", "youtubeSignupRequired",
               "accountClosed", "accountSuspended", "accessNotConfigured"}  # fmt: skip
_AUTH = {"authError", "invalidCredentials", "unauthorized"}


def classify(status: int, reasons: set[str], *, session: bool = False) -> PublishErrorCode:
    """Google's HTTP status and error reasons → the contract's code."""
    if status == 401 or reasons & _AUTH:
        return PublishErrorCode.AUTHENTICATION_REQUIRED
    if reasons & _QUOTA:
        return PublishErrorCode.QUOTA_EXCEEDED
    if status == 429 or reasons & _RATE:
        return PublishErrorCode.RATE_LIMITED
    if status == 403 or reasons & _PERMISSION:
        return PublishErrorCode.PERMISSION_DENIED
    if session and status in (404, 410):
        return PublishErrorCode.UPLOAD_SESSION_EXPIRED
    if status == 400:
        return PublishErrorCode.INVALID_METADATA
    return PublishErrorCode.PROVIDER_ERROR


def _reasons(response: httpx.Response) -> set[str]:
    try:
        errors = response.json().get("error", {}).get("errors", [])
        return {str(e.get("reason")) for e in errors if isinstance(e, dict) and e.get("reason")}
    except (ValueError, AttributeError):
        return set()


def _refresh_with_google(settings: Settings) -> Callable[[str], str]:
    def refresh(refresh_token: str) -> str:
        from google.auth.exceptions import RefreshError, TransportError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            scopes=[UPLOAD_SCOPE],
        )
        try:
            credentials.refresh(Request())
        except RefreshError:
            # invalid_grant and friends: consent revoked or expired.
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED) from None
        except TransportError:
            raise PublishProviderError(PublishErrorCode.NETWORK_ERROR) from None
        if not credentials.token:
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED)
        return credentials.token

    return refresh


class YouTubeProvider:
    name = "youtube"

    def __init__(
        self,
        refresh: Callable[[str], str],
        *,
        client: httpx.Client | None = None,
        upload_url: str = UPLOAD_URL,
        videos_url: str = VIDEOS_URL,
    ) -> None:
        self._refresh = refresh
        self._client = client or httpx.Client(timeout=httpx.Timeout(120, connect=10))
        self._upload_url = upload_url
        self._videos_url = videos_url

    @classmethod
    def from_settings(cls, settings: Settings) -> "YouTubeProvider":
        return cls(_refresh_with_google(settings))

    # --- HTTP ------------------------------------------------------------------------------

    def _send(self, method: str, url: str, *, session: bool = False, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            logger.warning("YouTube request failed: %s", type(error).__name__)
            raise PublishProviderError(PublishErrorCode.NETWORK_ERROR) from None
        if response.status_code >= 400:
            reasons = _reasons(response)
            code = classify(response.status_code, reasons, session=session)
            logger.warning(
                "YouTube answered %s (%s): %s",
                response.status_code,
                ",".join(sorted(reasons)) or "no reason",
                code,
            )
            raise PublishProviderError(code)
        return response

    @staticmethod
    def _headers(auth: ProviderAuth) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth.access_token}"}

    # --- the contract ----------------------------------------------------------------------

    def authorize(self, refresh_token: str) -> ProviderAuth:
        if not refresh_token:
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED)
        return ProviderAuth(self._refresh(refresh_token))

    def start_upload(self, auth: ProviderAuth, request: VideoRequest) -> str:
        body = {
            "snippet": {
                "title": request.title,
                "description": request.description,
                "tags": list(request.tags),
                "categoryId": request.category_id,
            },
            "status": {
                "privacyStatus": request.privacy,
                "selfDeclaredMadeForKids": request.made_for_kids,
            },
        }
        response = self._send(
            "POST",
            self._upload_url,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                **self._headers(auth),
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(request.size_bytes),
                "X-Upload-Content-Type": request.content_type,
            },
            content=json.dumps(body, ensure_ascii=False).encode(),
        )
        location = response.headers.get("location", "")
        if not location.startswith("https://"):
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR)
        return location

    def query_upload(self, auth: ProviderAuth, session_uri: str, total: int) -> UploadProgress:
        response = self._send(
            "PUT",
            session_uri,
            session=True,
            headers={**self._headers(auth), "Content-Range": f"bytes */{total}"},
            content=b"",
        )
        return self._progress(response)

    def upload_chunk(
        self, auth: ProviderAuth, session_uri: str, data: bytes, offset: int, total: int
    ) -> UploadProgress:
        if not data or offset + len(data) > total:
            raise ValueError("chunk outside the upload")
        end = offset + len(data) - 1
        response = self._send(
            "PUT",
            session_uri,
            session=True,
            headers={**self._headers(auth), "Content-Range": f"bytes {offset}-{end}/{total}"},
            content=data,
        )
        return self._progress(response)

    def video_status(self, auth: ProviderAuth, video_id: str) -> VideoStatus:
        try:
            response = self._send(
                "GET",
                self._videos_url,
                params={"part": "status,processingDetails", "id": video_id},
                headers=self._headers(auth),
            )
        except PublishProviderError as error:
            if error.code == PublishErrorCode.PERMISSION_DENIED:
                return VideoStatus(UploadState.UNKNOWN)  # upload-only scope: honest unknown
            raise
        items = response.json().get("items") or []
        if not items:
            return VideoStatus(UploadState.DELETED)
        status = items[0].get("status") or {}
        upload = status.get("uploadStatus")
        state = {
            "uploaded": UploadState.UPLOADED,
            "processed": UploadState.PROCESSED,
            "failed": UploadState.FAILED,
            "rejected": UploadState.REJECTED,
            "deleted": UploadState.DELETED,
        }.get(upload, UploadState.UNKNOWN)
        reason = status.get("failureReason") or status.get("rejectionReason")
        return VideoStatus(state, status.get("privacyStatus"), reason)

    # --- helpers ---------------------------------------------------------------------------

    @staticmethod
    def _progress(response: httpx.Response) -> UploadProgress:
        if response.status_code in (200, 201):
            try:
                video = response.json()
            except ValueError:
                raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR) from None
            video_id = video.get("id")
            if not isinstance(video_id, str) or not video_id:
                raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR)
            snippet = video.get("snippet") or {}
            total = int(response.request.headers.get("content-range", "/0").rsplit("/", 1)[-1])
            return UploadProgress(
                confirmed_bytes=total,
                video_id=video_id,
                channel_id=snippet.get("channelId"),
                channel_title=snippet.get("channelTitle"),
            )
        if response.status_code == 308:
            match = _RANGE.match(response.headers.get("range", ""))
            return UploadProgress(confirmed_bytes=int(match.group(1)) + 1 if match else 0)
        raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR)
