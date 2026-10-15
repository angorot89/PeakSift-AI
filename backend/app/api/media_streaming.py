"""Private media streaming shared by every media endpoint (source videos, clips, shorts,
audio assets).

One implementation of single-range HTTP Range support so every private media endpoint
behaves identically, whichever storage backend holds the bytes: ``200`` for full content,
``206`` with ``Content-Range`` for a satisfiable byte range (including suffix ranges),
``416`` with ``bytes */size`` for an unsatisfiable one; ``Accept-Ranges: bytes`` and
``Cache-Control: private, no-store`` always. Objects are read in 1 MiB chunks through the
storage contract (a ranged GET on S3) — nothing is loaded into memory whole. Callers pass
the stored key after checking ownership; no key or path ever comes from the request.
"""

import re
from urllib.parse import quote

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.services.storage import InvalidStorageKey, ObjectNotFound, StorageProvider

_RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return (start, end) inclusive for a single byte range, or None to serve everything.

    Multiple ranges and malformed headers are ignored (full content is served, as the
    HTTP spec allows). An unsatisfiable range raises 416.
    """
    if not header:
        return None
    match = _RANGE_PATTERN.match(header.strip())
    if not match or size == 0:
        return None
    first, last = match.groups()
    if first == "" and last == "":
        return None
    if first == "":
        # Suffix range: the last N bytes.
        length = min(int(last), size)
        return size - length, size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, end


def content_disposition(filename: str, *, attachment: bool = False) -> str:
    """RFC 6266 header with an ASCII fallback and a UTF-8 ``filename*``."""
    kind = "attachment" if attachment else "inline"
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "video"
    ascii_name = "".join(ch for ch in ascii_name if ch.isprintable() and ch not in "\\/")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def object_present(storage: StorageProvider, key: str | None) -> bool:
    """Whether ``key`` is a valid key with an object behind it.

    An unreachable backend raises ``StorageUnavailable`` (a 503) rather than answering
    "missing", so an outage never turns a ready artifact into a failure.
    """
    if not key:
        return False
    try:
        return storage.exists(key)
    except InvalidStorageKey:
        return False


def stream_object(
    storage: StorageProvider,
    key: str,
    request: Request,
    *,
    media_type: str,
    filename: str,
    attachment: bool = False,
) -> StreamingResponse:
    """Stream the object at ``key`` honouring a single ``Range`` header.

    The caller has already checked ownership and that the object exists; one that vanished
    since is a 404, and an unreachable backend raises ``StorageUnavailable`` (a 503).
    """
    missing = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    try:
        size = storage.size(key)
    except (ObjectNotFound, InvalidStorageKey):
        raise missing from None
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": content_disposition(filename, attachment=attachment),
        "X-Content-Type-Options": "nosniff",
    }
    byte_range = parse_range(request.headers.get("range"), size)
    if byte_range is None:
        start, end, status_code = 0, size - 1, status.HTTP_200_OK
    else:
        (start, end), status_code = byte_range, status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    try:
        # The first request happens here, so a missing object is still a clean 404.
        body = storage.iter_range(key, start, end) if size else iter(())
    except ObjectNotFound:
        raise missing from None
    return StreamingResponse(body, status_code=status_code, media_type=media_type, headers=headers)
