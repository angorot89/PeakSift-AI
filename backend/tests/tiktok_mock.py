"""A mock of TikTok's OAuth and Content Posting endpoints for httpx (no network).

Implements what the documentation states: the token endpoint (authorization code and refresh,
**rotating** the refresh token on every refresh), ``creator_info/query``, ``video/init`` with
its chunk-plan rules (``total_chunk_count = floor(video_size / chunk_size)``, 5–64 MB chunks, a
file under 5 MB as one chunk), sequential ``PUT`` chunks answered ``206`` then ``201``
(``416`` for a range that does not continue the upload, ``403`` for an expired URL), and
``status/fetch``. Every request is recorded for assertions.
"""

import itertools
import json
import re
from urllib.parse import parse_qs

import httpx

API = "https://open.tiktokapis.com"
TOKEN_URL = f"{API}/v2/oauth/token/"
REVOKE_URL = f"{API}/v2/oauth/revoke/"
INIT_URL = f"{API}/v2/post/publish/video/init/"
STATUS_URL = f"{API}/v2/post/publish/status/fetch/"
CREATOR_URL = f"{API}/v2/post/publish/creator_info/query/"
UPLOAD_HOST = "open-upload.tiktokapis.test"
MIN_CHUNK, MAX_CHUNK = 5 * 1024 * 1024, 64_000_000
_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def api_error(status: int, code: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": code, "message": "TikTok says no", "log_id": "log-1"}}
    )


def ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "error": {"code": "ok", "message": ""}})


class MockTikTok:
    def __init__(self, *, processing_polls: int = 1) -> None:
        self.refresh_tokens: set[str] = {"rt-0"}
        self.access_tokens: set[str] = set()
        self.codes: dict[str, str] = {"good-code": "video.publish"}
        self.revoked: list[str] = []
        self.publishes: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.next_responses: list[httpx.Response] = []  # injected answers, first in first out
        self.processing_polls = processing_polls
        self.privacy_levels = ["SELF_ONLY"]
        self._ids = itertools.count(1)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    # --- helpers ---------------------------------------------------------------------

    def _issue(self, scope: str = "video.publish") -> dict:
        n = next(self._ids)
        access, refresh = f"at-{n}", f"rt-{n}"
        self.access_tokens.add(access)
        self.refresh_tokens.add(refresh)
        return {"access_token": access, "expires_in": 7200, "refresh_token": refresh,
                "refresh_expires_in": 15552000, "open_id": "open-id-1", "scope": scope,
                "token_type": "Bearer"}  # fmt: skip

    def _authorized(self, request: httpx.Request) -> bool:
        return request.headers.get("Authorization", "")[7:] in self.access_tokens

    def calls(self, url: str) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url).split("?")[0] == url]

    # --- the endpoints ---------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.next_responses:
            return self.next_responses.pop(0)
        url = str(request.url).split("?")[0]
        if url == TOKEN_URL:
            return self._token(request)
        if url == REVOKE_URL:
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200, json={})
        if request.url.host == UPLOAD_HOST:
            return self._upload(request)
        if not self._authorized(request):
            return api_error(401, "access_token_invalid")
        if url == CREATOR_URL:
            return ok({"creator_nickname": "Amine", "creator_username": "amine.clips",
                       "creator_avatar_url": "https://example.test/a.jpg",
                       "privacy_level_options": self.privacy_levels, "comment_disabled": False,
                       "duet_disabled": True, "stitch_disabled": False,
                       "max_video_post_duration_sec": 600})  # fmt: skip
        if url == INIT_URL:
            return self._init(request)
        if url == STATUS_URL:
            return self._status(request)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if form.get("client_key") != "client-key" or form.get("client_secret") != "client-secret":
            return httpx.Response(400, json={"error": "invalid_client", "log_id": "l"})
        if form.get("grant_type") == "authorization_code":
            scope = self.codes.pop(form.get("code", ""), None)
            if (
                scope is None
                or form.get("redirect_uri") != "https://api.example.test/publishing/tiktok/callback"
            ):
                return httpx.Response(400, json={"error": "invalid_grant", "log_id": "l"})
            return httpx.Response(200, json=self._issue(scope))
        token = form.get("refresh_token")
        if form.get("grant_type") != "refresh_token" or token not in self.refresh_tokens:
            return httpx.Response(400, json={"error": "invalid_grant", "log_id": "l"})
        self.refresh_tokens.discard(token)  # rotation: the old refresh token is dead now
        return httpx.Response(200, json=self._issue())

    def _init(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        post, source = body["post_info"], body["source_info"]
        size, chunk, count = source["video_size"], source["chunk_size"], source["total_chunk_count"]
        if post["privacy_level"] not in self.privacy_levels:
            return api_error(400, "privacy_level_option_mismatch")
        single = size < MIN_CHUNK and chunk == size and count == 1
        planned = MIN_CHUNK <= chunk <= MAX_CHUNK and count == max(1, size // chunk)
        if source["source"] != "FILE_UPLOAD" or not (single or planned) or count > 1000:
            return api_error(400, "invalid_param")
        n = next(self._ids)
        publish_id = f"v_pub_file~v2-{n}"
        self.publishes[publish_id] = {"post": post, "size": size, "chunk": chunk, "count": count,
                                      "received": 0, "bytes": b"", "polls": 0, "expired": False,
                                      "fail_reason": None}  # fmt: skip
        upload_url = f"https://{UPLOAD_HOST}/video/?upload_id={n}&upload_token=secret-{n}"
        return ok({"publish_id": publish_id, "upload_url": upload_url})

    def _publish_for(self, request: httpx.Request) -> tuple[str, dict] | None:
        upload_id = request.url.params.get("upload_id")
        for publish_id, publish in self.publishes.items():
            if publish_id.endswith(f"-{upload_id}"):
                return publish_id, publish
        return None

    def _upload(self, request: httpx.Request) -> httpx.Response:
        found = self._publish_for(request)
        if found is None:
            return httpx.Response(404)
        _, publish = found
        if publish["expired"]:
            return httpx.Response(403)
        match = _RANGE.match(request.headers.get("Content-Range", ""))
        if not match:
            return httpx.Response(400)
        first, last, total = (int(g) for g in match.groups())
        data = request.content
        index = first // publish["chunk"]
        is_last = index >= publish["count"] - 1
        expected = total - first if is_last else publish["chunk"]
        if (first != publish["received"] or total != publish["size"]
                or len(data) != last - first + 1 or len(data) != expected):  # fmt: skip
            return httpx.Response(
                416, headers={"Content-Range": f"bytes 0-{publish['received'] - 1}/{total}"}
            )
        publish["received"] += len(data)
        publish["bytes"] += data
        done = publish["received"] == publish["size"]
        return httpx.Response(
            201 if done else 206,
            headers={"Content-Range": f"bytes 0-{publish['received'] - 1}/{total}"},
        )

    def _status(self, request: httpx.Request) -> httpx.Response:
        publish = self.publishes.get(json.loads(request.content).get("publish_id"))
        if publish is None:
            return api_error(400, "invalid_publish_id")
        if publish["fail_reason"]:
            return ok({"status": "FAILED", "fail_reason": publish["fail_reason"],
                       "uploaded_bytes": publish["received"]})  # fmt: skip
        if publish["received"] < publish["size"]:
            return ok({"status": "PROCESSING_UPLOAD", "uploaded_bytes": publish["received"]})
        publish["polls"] += 1
        if publish["polls"] <= self.processing_polls:
            return ok({"status": "PROCESSING_UPLOAD", "uploaded_bytes": publish["received"]})
        return ok({"status": "PUBLISH_COMPLETE", "uploaded_bytes": publish["received"],
                   "publicaly_available_post_id": []})  # fmt: skip
