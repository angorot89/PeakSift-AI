"""An in-memory publishing provider that behaves like YouTube's resumable upload.

Used by the test suite and, outside production only (``PUBLISHING_PROVIDER=fake``), to
exercise the whole publishing flow without a Google account. Nothing leaves the process;
video ids start with ``fake-`` and the UI labels such results as simulated. Production
refuses to start with it.

Behaviour that matters for the pipeline is modelled: a session accepts bytes only at the
offset it has confirmed, may confirm fewer bytes than were sent, can be queried after an
interruption, can expire, creates the video exactly once when the last byte arrives, and
reports processing over successive status calls. Failures can be scripted per operation.
"""

import hashlib
import itertools
import secrets
from collections import defaultdict
from collections.abc import Iterable

from app.services.publishing.provider import (
    ProviderAuth,
    PublishErrorCode,
    PublishProviderError,
    UploadProgress,
    UploadState,
    VideoRequest,
    VideoStatus,
)


class FakePublishingProvider:
    name = "fake"

    def __init__(
        self,
        *,
        confirm_at_most: int | None = None,
        processing_polls: int = 1,
        final_state: UploadState = UploadState.PROCESSED,
    ) -> None:
        self.confirm_at_most = confirm_at_most  # simulate partial acceptance of a chunk
        self.processing_polls = processing_polls
        self.final_state = final_state
        self.sessions: dict[str, dict] = {}
        self.videos: dict[str, dict] = {}
        self.revoked_tokens: set[str] = set()
        self.calls: list[str] = []
        self._failures: dict[str, list[PublishErrorCode | None]] = defaultdict(list)
        self._ids = itertools.count(1)

    # --- scripting ------------------------------------------------------------------------

    def fail(self, operation: str, codes: Iterable[PublishErrorCode | None]) -> None:
        """The next calls of ``operation`` raise these codes in order (None: succeed)."""
        self._failures[operation].extend(codes)

    def expire(self, session_uri: str) -> None:
        self.sessions.pop(session_uri, None)

    def _maybe_fail(self, operation: str) -> None:
        self.calls.append(operation)
        if self._failures[operation]:
            code = self._failures[operation].pop(0)
            if code is not None:
                raise PublishProviderError(code)

    # --- the contract ----------------------------------------------------------------------

    def authorize(self, refresh_token: str) -> ProviderAuth:
        self._maybe_fail("authorize")
        if not refresh_token or refresh_token in self.revoked_tokens:
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED)
        digest = hashlib.sha256(refresh_token.encode()).hexdigest()[:16]
        return ProviderAuth(f"fake-access-{digest}")

    def start_upload(self, auth: ProviderAuth, request: VideoRequest) -> str:
        self._check(auth)
        self._maybe_fail("start_upload")
        if not request.title or request.size_bytes <= 0:
            raise PublishProviderError(PublishErrorCode.INVALID_METADATA)
        uri = f"https://upload.fake.invalid/session/{secrets.token_urlsafe(24)}"
        self.sessions[uri] = {"received": bytearray(), "total": request.size_bytes,
                              "request": request, "video_id": None}  # fmt: skip
        return uri

    def query_upload(self, auth: ProviderAuth, session_uri: str, total: int) -> UploadProgress:
        self._check(auth)
        self._maybe_fail("query_upload")
        return self._progress(self._session(session_uri))

    def upload_chunk(
        self, auth: ProviderAuth, session_uri: str, data: bytes, offset: int, total: int
    ) -> UploadProgress:
        self._check(auth)
        self._maybe_fail("upload_chunk")
        session = self._session(session_uri)
        if total != session["total"] or offset != len(session["received"]):
            # Like YouTube: bytes are accepted only where the session left off.
            return self._progress(session)
        accepted = data if self.confirm_at_most is None else data[: self.confirm_at_most]
        session["received"].extend(accepted)
        if len(session["received"]) == session["total"] and session["video_id"] is None:
            video_id = f"fake-{next(self._ids):06d}"
            session["video_id"] = video_id
            self.videos[video_id] = {"request": session["request"],
                                     "data": bytes(session["received"]), "polls": 0}  # fmt: skip
        return self._progress(session)

    def video_status(self, auth: ProviderAuth, video_id: str) -> VideoStatus:
        self._check(auth)
        self._maybe_fail("video_status")
        video = self.videos.get(video_id)
        if video is None:
            return VideoStatus(UploadState.DELETED)
        video["polls"] += 1
        if video["polls"] < self.processing_polls:
            return VideoStatus(UploadState.UPLOADED, video["request"].privacy)
        reason = None if self.final_state == UploadState.PROCESSED else "fakeRejection"
        return VideoStatus(self.final_state, video["request"].privacy, reason)

    # --- helpers ---------------------------------------------------------------------------

    def _check(self, auth: ProviderAuth) -> None:
        if not auth.access_token.startswith("fake-access-"):
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED)

    def _session(self, uri: str) -> dict:
        session = self.sessions.get(uri)
        if session is None:
            raise PublishProviderError(PublishErrorCode.UPLOAD_SESSION_EXPIRED)
        return session

    @staticmethod
    def _progress(session: dict) -> UploadProgress:
        video_id = session["video_id"]
        return UploadProgress(
            confirmed_bytes=len(session["received"]),
            video_id=video_id,
            channel_id="fake-channel" if video_id else None,
            channel_title="Simulated channel" if video_id else None,
        )
