"""Private media streaming shared by source-video preview and generated-clip delivery.

One implementation of single-range HTTP Range support so every private media endpoint
behaves identically: ``200`` for full content, ``206`` with ``Content-Range`` for a
satisfiable byte range (including suffix ranges), ``416`` with ``bytes */size`` for an
unsatisfiable one; ``Accept-Ranges: bytes`` and ``Cache-Control: private, no-store``
always. Files are read in 1 MiB chunks — nothing is loaded into memory whole. Callers
resolve the path through ``LocalMediaStorage.path_for`` after checking ownership; no
path ever comes from the request.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse

CHUNK_SIZE = 1024 * 1024
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


def iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    """Yield bytes [start, end] in chunks. The file closes when the generator ends or is closed."""
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def content_disposition(filename: str, *, attachment: bool = False) -> str:
    """RFC 6266 header with an ASCII fallback and a UTF-8 ``filename*``."""
    kind = "attachment" if attachment else "inline"
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "video"
    ascii_name = "".join(ch for ch in ascii_name if ch.isprintable() and ch not in "\\/")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def stream_file(
    path: Path,
    request: Request,
    *,
    media_type: str,
    filename: str,
    attachment: bool = False,
) -> StreamingResponse:
    """Stream ``path`` honouring a single ``Range`` header."""
    size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": content_disposition(filename, attachment=attachment),
        "X-Content-Type-Options": "nosniff",
    }
    byte_range = parse_range(request.headers.get("range"), size)
    if byte_range is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            iter_file(path, 0, size - 1), media_type=media_type, headers=headers
        )

    start, end = byte_range
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        iter_file(path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )
