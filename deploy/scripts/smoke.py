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

# V1.1 visual assets on object storage: a generated PNG (standard library only) is validated,
# thumbnailed and stored in the private bucket, streamed with Range, then deleted.
def tiny_png(width: int = 64, height: int = 48) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + bytes((200, 40, 40)) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))  # fmt: skip


status, _, body = call("POST", "/api/projects", body={"name": "Smoke visuals"})
visual_project = json.loads(body or b"{}").get("id")
check("a project for visual assets", status == 201 and bool(visual_project))
if visual_project:
    png = tiny_png()
    boundary = uuid.uuid4().hex
    multipart = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"smoke.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n".encode() + png + f"\r\n--{boundary}--\r\n".encode()
    )
    base = f"/api/projects/{visual_project}/visual-assets"
    status, _, body = call("POST", base, raw=multipart,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})  # fmt: skip
    asset = json.loads(body or b"{}")
    check("visual asset validated and stored", status == 201 and asset.get("kind") == "image"
          and asset.get("has_thumbnail") is True, f"{status} {body[:160]!r}")  # fmt: skip
    if asset.get("id"):
        status, _, thumb = call("GET", f"{base}/{asset['id']}/thumbnail")
        image = thumb[:3] == b"\xff\xd8\xff" or thumb[:4] == b"\x89PNG"  # JPEG or PNG
        check("thumbnail served from object storage", status == 200 and image, f"{status}")
        status, _, part = call("GET", f"{base}/{asset['id']}/content", headers={"Range": "bytes=0-31"})
        check("visual Range request served", status == 206 and len(part) == 32, f"{status}")
        status, _, body = call("GET", "/api/visual-layout")
        check("visual layout published", status == 200 and b"inset_width_fraction" in body)
        status, _, body = call("DELETE", f"{base}/{asset['id']}")
        removed = json.loads(body or b"{}").get("media_files_removed")
        check("unused visual deleted with its thumbnail", status == 200 and removed == 2, f"{status} {removed}")

# Auto Edit: the recipes are served, and planning answers honestly without a clip.
status, _, body = call("GET", "/api/auto-edit/recipes")
recipes = [r.get("name") for r in json.loads(body or b"[]")] if status == 200 else []
check("Auto Edit recipes served", recipes == ["clean", "punchy", "story", "minimal"], f"{status} {recipes}")
if visual_project:
    missing = f"/api/projects/{visual_project}/videos/{uuid.uuid4()}/clips/{uuid.uuid4()}/auto-edits"
    status, _, _ = call("POST", missing, body={"recipe": "clean"})
    check("Auto Edit on a missing clip is a 404", status == 404, str(status))

print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
