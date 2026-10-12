"""Validation and storage of uploaded source videos."""

from pathlib import PurePosixPath

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import Project, Video
from app.services.storage import FileTooLarge, LocalMediaStorage

# Extension -> MIME types a browser may legitimately send for it. The first entry is
# what we store, so the content type on record is canonical rather than client-chosen.
ALLOWED_VIDEO_TYPES: dict[str, tuple[str, ...]] = {
    ".mp4": ("video/mp4",),
    ".mov": ("video/quicktime",),
    ".webm": ("video/webm",),
}
# Browsers (and curl) sometimes send these instead of a real video type.
GENERIC_CONTENT_TYPES = {"", "application/octet-stream"}

MAX_FILENAME_LENGTH = 255
_WINDOWS_RESERVED = set('<>:"|?*')


class UploadValidationError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def sanitize_filename(raw: str | None) -> str:
    """Reduce a browser-supplied name to a safe display name.

    Only the final path component survives (both separators), control and
    unprintable characters are dropped, and the result is capped at 255 characters
    while keeping the extension. This is metadata only — never a filesystem path.
    """
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in _WINDOWS_RESERVED)
    name = name.strip(" .")
    if len(name) > MAX_FILENAME_LENGTH:
        suffix = PurePosixPath(name).suffix[:16]
        name = name[: MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return name or "video"


def validate_upload(filename: str | None, content_type: str | None) -> tuple[str, str, str]:
    """Return (safe_filename, extension, canonical_content_type) or raise 415."""
    safe_name = sanitize_filename(filename)
    extension = PurePosixPath(safe_name).suffix.lower()
    if extension not in ALLOWED_VIDEO_TYPES:
        allowed = ", ".join(sorted(ALLOWED_VIDEO_TYPES))
        raise UploadValidationError(415, f"Unsupported file type. Use one of: {allowed}")

    declared = (content_type or "").split(";", 1)[0].strip().lower()
    accepted = ALLOWED_VIDEO_TYPES[extension]
    if declared not in accepted and declared not in GENERIC_CONTENT_TYPES:
        raise UploadValidationError(415, "The file's content type does not match its extension")

    return safe_name, extension, accepted[0]


def check_declared_size(content_length: str | None, limit: int) -> None:
    """Reject early when the request already announces a body beyond the limit."""
    if content_length is None:
        return
    try:
        declared = int(content_length)
    except ValueError:
        return
    # Multipart framing adds a little; allow generous slack so legitimate uploads pass.
    if declared > limit + 64 * 1024:
        raise UploadValidationError(413, too_large_message(limit))


def too_large_message(limit: int) -> str:
    return f"File is too large. The maximum is {limit // (1024 * 1024)} MB"


def store_upload(
    db: Session,
    storage: LocalMediaStorage,
    project: Project,
    upload: UploadFile,
    *,
    max_bytes: int,
) -> Video:
    """Stream the upload into storage and record it. Leaves nothing behind on failure."""
    safe_name, extension, content_type = validate_upload(upload.filename, upload.content_type)
    key = storage.generate_key(extension)

    try:
        size = storage.save(upload.file, key, max_bytes=max_bytes)
    except FileTooLarge as error:
        raise UploadValidationError(413, too_large_message(error.limit)) from None

    if size == 0:
        storage.delete(key)
        raise UploadValidationError(400, "The uploaded file is empty")

    video = Video(
        project=project,
        original_filename=safe_name,
        storage_key=key,
        content_type=content_type,
        file_size=size,
    )
    db.add(video)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return video
