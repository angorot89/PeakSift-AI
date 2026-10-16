#!/usr/bin/env python3
"""Smoke-test a running PeakSift stack through its HTTPS proxy (stdlib only).

    python3 deploy/scripts/smoke.py https://localhost [video.mp4]

Checks the HTTP→HTTPS redirect, readiness, the frontend, hidden API docs, registration with
a Secure HttpOnly session cookie and, given a small MP4, an upload that is probed and
served back byte-for-byte with Range. Certificates are not verified (local self-signed).
"""

import http.cookiejar
import json
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

BASE = sys.argv[1].rstrip("/")
VIDEO = sys.argv[2] if len(sys.argv) > 2 else None
CONTEXT = ssl.create_default_context()
CONTEXT.check_hostname = False
CONTEXT.verify_mode = ssl.CERT_NONE
JAR = http.cookiejar.CookieJar()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=CONTEXT), urllib.request.HTTPCookieProcessor(JAR), NoRedirect
)
failures: list[str] = []


def check(name: str, ok: bool, info: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}{f' — {info}' if info else ''}")
    if not ok:
        failures.append(name)


def call(method: str, path: str, *, body=None, headers=None, raw: bytes | None = None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(f"{BASE}{path}" if path.startswith("/") else path,
                                     data=data, method=method, headers=headers or {})  # fmt: skip
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        response = OPENER.open(request, timeout=60)
    except urllib.error.HTTPError as error:
        response = error
    return response.status, dict(response.headers), response.read()


host = urlsplit(BASE).hostname
status, headers, _ = call("GET", f"http://{host}/projects")
check("http redirects to https", status == 301 and headers.get("Location", "").startswith("https://"),
      f"{status} {headers.get('Location')}")  # fmt: skip

status, headers, body = call("GET", "/api/health/ready")
ready = json.loads(body or b"{}")
check("api ready through the proxy", status == 200 and ready.get("status") == "ready", body.decode()[:200])
check("readiness covers database, redis, storage",
      set(ready.get("checks", {})) == {"database", "redis", "storage"})  # fmt: skip
check("responses carry a request id", bool(headers.get("x-request-id") or headers.get("X-Request-ID")))

status, _, body = call("GET", "/login")
check("frontend serves the login page", status == 200 and b"<html" in body.lower())
status, _, _ = call("GET", "/api/docs")
check("interactive API docs are off in production", status == 404, str(status))

email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
status, headers, body = call("POST", "/api/auth/register",
                             body={"email": email, "password": "smoke-test-password-1"})  # fmt: skip
cookie = headers.get("set-cookie") or headers.get("Set-Cookie") or ""
check("registration works", status == 201, f"{status} {body[:120]!r}")
check("session cookie is Secure and HttpOnly", "Secure" in cookie and "HttpOnly" in cookie)

if VIDEO:
    status, _, body = call("POST", "/api/projects", body={"name": "Smoke"})
    project = json.loads(body)["id"]
    data = open(VIDEO, "rb").read()
    boundary = uuid.uuid4().hex
    multipart = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"smoke.mp4\"\r\n"
        f"Content-Type: video/mp4\r\n\r\n".encode() + data + f"\r\n--{boundary}--\r\n".encode()
    )
    status, _, body = call("POST", f"/api/projects/{project}/videos", raw=multipart,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})  # fmt: skip
    video = json.loads(body or b"{}")
    check("upload is stored and probed", status == 201 and video.get("status") == "ready",
          f"{status} {body[:200]!r}")  # fmt: skip
    if video.get("id"):
        status, headers, part = call("GET", f"/api/videos/{video['id']}/content",
                                     headers={"Range": "bytes=0-99"})  # fmt: skip
        check("Range request served from object storage",
              status == 206 and part == data[:100], f"{status} {len(part)} bytes")  # fmt: skip
        status, _, full = call("GET", f"/api/videos/{video['id']}/content")
        check("full download is byte-identical", status == 200 and full == data)

print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
