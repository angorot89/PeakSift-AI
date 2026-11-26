"""A mock of the Meta endpoints Instagram Reels publishing uses (Graph API v27.0), for httpx.

What the documentation states: the code and long-lived token exchanges, ``/me/permissions``,
``/me/accounts`` with each Page's ``access_token`` and ``instagram_business_account``,
resumable Reels containers (``id`` and ``uri``), the single upload to ``rupload.facebook.com``
with ``offset`` and ``file_size`` headers, container ``status_code`` (``IN_PROGRESS`` →
``FINISHED`` → ``PUBLISHED``, or ``ERROR`` / ``EXPIRED``) and ``media_publish``.
Every request is recorded for assertions.
"""

import itertools
from urllib.parse import parse_qs

import httpx

GRAPH = "https://graph.facebook.com/v27.0"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload/v27.0/"
REDIRECT = "https://api.example.test/publishing/instagram/callback"
IG_ID = "17841400000000001"


def graph_error(status: int, code: int, transient: bool = False) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": "Meta says no", "type": "OAuthException", "code": code,
                        "is_transient": transient, "fbtrace_id": "trace-1"}},
    )  # fmt: skip


class MockMeta:
    def __init__(self, *, processing_polls: int = 1) -> None:
        self.codes = {"good-code"}
        self.page_token = "page-token-1"
        self.granted = ["instagram_basic", "instagram_content_publish", "pages_show_list",
                        "pages_read_engagement"]  # fmt: skip
        self.pages = [
            {"id": "100", "name": "Page without Instagram", "access_token": "other-page-token"},
            {"id": "101", "name": "Amine Clips", "access_token": self.page_token,
             "instagram_business_account": {"id": IG_ID, "username": "amine.clips"}},
        ]  # fmt: skip
        self.containers: dict[str, dict] = {}
        self.published: list[str] = []
        self.requests: list[httpx.Request] = []
        self.next_responses: list[httpx.Response] = []
        self.processing_polls = processing_polls
        self._ids = itertools.count(18000000000000001)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def calls(self, method: str, suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(suffix)]

    def _token(self, request: httpx.Request) -> str:
        return request.headers.get("Authorization", "").removeprefix("OAuth ")

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.next_responses:
            return self.next_responses.pop(0)
        url = str(request.url).split("?")[0]
        params = dict(request.url.params)
        if url == f"{GRAPH}/oauth/access_token":
            if (
                params.get("client_id") != "1234567890"
                or params.get("client_secret") != "app-secret"
            ):
                return graph_error(400, 101)
            if params.get("grant_type") == "fb_exchange_token":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "long-user-token",
                        "token_type": "bearer",
                        "expires_in": 5183944,
                    },
                )
            if params.get("code") not in self.codes or params.get("redirect_uri") != REDIRECT:
                return graph_error(400, 100)
            self.codes.discard(params["code"])
            return httpx.Response(
                200,
                json={
                    "access_token": "short-user-token",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            )
        if url == f"{GRAPH}/me/permissions":
            if self._token(request) != "long-user-token":
                return graph_error(401, 190)
            return httpx.Response(
                200, json={"data": [{"permission": p, "status": "granted"} for p in self.granted]}
            )
        if url == f"{GRAPH}/me/accounts":
            if self._token(request) != "long-user-token":
                return graph_error(401, 190)
            return httpx.Response(200, json={"data": self.pages})
        if url.startswith(RUPLOAD):
            return self._upload(request, url.removeprefix(RUPLOAD))
        if self._token(request) != self.page_token:
            return graph_error(401, 190)
        if url == f"{GRAPH}/{IG_ID}/media" and request.method == "POST":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("media_type") != "REELS" or form.get("upload_type") != "resumable":
                return graph_error(400, 100)
            container = str(next(self._ids))
            self.containers[container] = {
                "caption": form.get("caption", ""),
                "bytes": b"",
                "status": "IN_PROGRESS",
                "uploaded": False,
                "polls": 0,
            }
            return httpx.Response(200, json={"id": container, "uri": f"{RUPLOAD}{container}"})
        if url == f"{GRAPH}/{IG_ID}/media_publish" and request.method == "POST":
            container = parse_qs(request.content.decode()).get("creation_id", [""])[0]
            entry = self.containers.get(container)
            if entry is None or entry["status"] != "FINISHED":
                return graph_error(400, 9007)
            entry["status"] = "PUBLISHED"
            self.published.append(container)
            return httpx.Response(200, json={"id": str(next(self._ids))})
        container = url.removeprefix(f"{GRAPH}/")
        if request.method == "GET" and container in self.containers:
            entry = self.containers[container]
            if entry["uploaded"] and entry["status"] == "IN_PROGRESS":
                entry["polls"] += 1
                if entry["polls"] > self.processing_polls:
                    entry["status"] = "FINISHED"
            return httpx.Response(200, json={"status_code": entry["status"], "id": container})
        return httpx.Response(404, json={"error": {"code": 803, "message": "not found"}})

    def _upload(self, request: httpx.Request, container: str) -> httpx.Response:
        entry = self.containers.get(container)
        if entry is None:
            return httpx.Response(400, json={"debug_info": {"retriable": False, "type": "x"}})
        if self._token(request) != self.page_token:
            return httpx.Response(401, json={"debug_info": {"retriable": False, "type": "auth"}})
        size = int(request.headers.get("file_size", "-1"))
        if request.headers.get("offset") != "0" or size != len(request.content):
            return httpx.Response(400, json={"debug_info": {"retriable": False, "type": "x"}})
        entry["bytes"], entry["uploaded"] = request.content, True
        return httpx.Response(200, json={"success": True, "message": "Upload successful."})
