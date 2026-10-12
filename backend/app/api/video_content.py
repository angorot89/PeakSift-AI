"""Authenticated streaming of a source video's bytes, with single-range support."""

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Storage
from app.models import Project, Video

router = APIRouter(prefix="/videos", tags=["videos"])

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


def content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "video"
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/{video_id}/content")
def video_content(
    video_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> StreamingResponse:
    video = db.scalar(
        select(Video).join(Project).where(Video.id == video_id, Project.user_id == current_user.id)
    )
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    path = storage.path_for(video.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video file not found")
    size = path.stat().st_size

    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": content_disposition(video.original_filename),
    }

    byte_range = parse_range(request.headers.get("range"), size)
    if byte_range is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            iter_file(path, 0, size - 1), media_type=video.content_type, headers=headers
        )

    start, end = byte_range
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        iter_file(path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=video.content_type,
        headers=headers,
    )
