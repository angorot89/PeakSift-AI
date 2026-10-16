"""A mock of YouTube's resumable upload endpoints for httpx (no network).

Implements the documented protocol: ``POST …/upload/youtube/v3/videos?uploadType=resumable``
returns a session ``Location``; ``PUT <session>`` with ``Content-Range: bytes a-b/total``
answers ``308`` + ``Range: bytes=0-N`` (or no Range when nothing is stored) until the last
byte, then ``201`` with the video resource; ``PUT`` with ``bytes */total`` reports progress;
``GET …/youtube/v3/videos`` reports status. Every request is recorded for assertions.
"""

import itertools
import json
import re

import httpx

from app.services.publishing.provider import PublishErrorCode, PublishProviderError, UploadState

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_QUERY = re.compile(r"^bytes \*/(\d+)$")


def google_error(status: int, reason: str, message: str = "Google says no") -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": status, "message": message, "errors": [{"reason": reason}]}},
    )


class MockYouTube:
    def __init__(self, *, processing_polls: int = 1, status_scope: bool = True) -> None:
        self.sessions: dict[str, dict] = {}
        self.videos: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.revoked: set[str] = set()
        self.processing_polls = processing_polls
        self.status_scope = status_scope  # False: the token cannot read videos (upload only)
        self.next_responses: list[httpx.Response] = []  # injected answers, first in first out
        self.confirm_at_most: int | None = None
        self._ids = itertools.count(1)

    # --- wiring ---------------------------------------------------------------------------

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def refresh(self, refresh_token: str) -> str:
        if refresh_token in self.revoked:
            raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED)
        return f"ya29.mock-{abs(hash(refresh_token)) % 10**8}"

    # --- the server -----------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not request.headers.get("authorization", "").startswith("Bearer ya29.mock-"):
            return google_error(401, "authError")
        if self.next_responses:
            return self.next_responses.pop(0)
        url = str(request.url)
        if request.method == "POST" and url.startswith(UPLOAD_URL):
            return self._start(request)
        if request.method == "PUT" and url in self.sessions:
            return self._put(request, self.sessions[url])
        if request.method == "PUT":
            return httpx.Response(404, json={"error": {"code": 404, "errors": []}})
        if request.method == "GET" and url.startswith(VIDEOS_URL):
            return self._status(request)
        return httpx.Response(400)

    def _start(self, request: httpx.Request) -> httpx.Response:
        assert request.url.params["uploadType"] == "resumable"
        body = json.loads(request.content)
        if not body["snippet"]["title"]:
            return google_error(400, "invalidTitle")
        upload_id = f"ADPy{len(self.sessions)}secret"
        uri = f"{UPLOAD_URL}?uploadType=resumable&part=snippet%2Cstatus&upload_id={upload_id}"
        self.sessions[uri] = {"received": bytearray(), "body": body, "video_id": None,
                              "total": int(request.headers["x-upload-content-length"])}  # fmt: skip
        return httpx.Response(200, headers={"Location": uri})

    def _put(self, request: httpx.Request, session: dict) -> httpx.Response:
        content_range = request.headers["content-range"]
        if query := _QUERY.match(content_range):
            assert int(query.group(1)) == session["total"]
            return self._answer(session)
        match = _RANGE.match(content_range)
        assert match, content_range
        start, end, total = map(int, match.groups())
        assert total == session["total"] and end - start + 1 == len(request.content)
        if start == len(session["received"]):
            data = request.content
            if self.confirm_at_most is not None:
                data = data[: self.confirm_at_most]
            session["received"].extend(data)
        if len(session["received"]) == total and session["video_id"] is None:
            video_id = f"vid{next(self._ids):08d}"
            session["video_id"] = video_id
            self.videos[video_id] = {"data": bytes(session["received"]),
                                     "body": session["body"], "polls": 0}  # fmt: skip
        return self._answer(session)

    def _answer(self, session: dict) -> httpx.Response:
        if session["video_id"]:
            body = session["body"]
            return httpx.Response(201, json={
                "id": session["video_id"],
                "snippet": {**body["snippet"], "channelId": "UCmock", "channelTitle": "Mock"},
                "status": {**body["status"], "uploadStatus": "uploaded"},
            })  # fmt: skip
        received = len(session["received"])
        headers = {"Range": f"bytes=0-{received - 1}"} if received else {}
        return httpx.Response(308, headers=headers)

    def _status(self, request: httpx.Request) -> httpx.Response:
        if not self.status_scope:
            return google_error(403, "insufficientPermissions")
        video = self.videos.get(request.url.params["id"])
        if video is None:
            return httpx.Response(200, json={"items": []})
        video["polls"] += 1
        state = "processed" if video["polls"] >= self.processing_polls else "uploaded"
        privacy = video["body"]["status"]["privacyStatus"]
        return httpx.Response(200, json={"items": [{
            "id": request.url.params["id"],
            "status": {"uploadStatus": state, "privacyStatus": privacy},
        }]})  # fmt: skip

    # --- test controls ------------------------------------------------------------------

    def expire(self, uri: str) -> None:
        self.sessions.pop(uri, None)


class YouTubeHarness:
    """The provider wired to a ``MockYouTube`` (the contract suite's interface)."""

    def __init__(self, processing_polls: int = 1, **_) -> None:
        from app.services.publishing.youtube import YouTubeProvider

        self.server = MockYouTube(processing_polls=processing_polls)
        self.provider = YouTubeProvider(self.server.refresh, client=self.server.client())

    def expire(self, uri: str) -> None:
        self.server.expire(uri)

    def revoke(self, token: str) -> None:
        self.server.revoked.add(token)

    def videos(self) -> dict[str, bytes]:
        return {vid: video["data"] for vid, video in self.server.videos.items()}


__all__ = ["MockYouTube", "UploadState", "YouTubeHarness", "google_error"]
