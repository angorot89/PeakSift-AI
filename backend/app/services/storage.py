"""Local filesystem media storage for development.

Files live under a configurable root (``MEDIA_ROOT``) and are addressed by *storage
keys* that the application generates (``videos/<uuid>.<ext>``). Browser-supplied
names are never used as paths. Production object storage (S3/R2) comes later and
will implement the same small surface: save / exists / delete / path_for.
"""

import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO

CHUNK_SIZE = 1024 * 1024  # 1 MiB

# Keys are relative, slash-separated, and made only of safe characters.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*(?:\.[A-Za-z0-9]{1,16})?$")
_EXTENSION_PATTERN = re.compile(r"^[A-Za-z0-9]{1,16}$")


class StorageError(Exception):
    """Base class for storage failures."""


class InvalidStorageKey(StorageError):
    """The key is malformed or would resolve outside the media root."""


class FileTooLarge(StorageError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"File exceeds the maximum size of {limit} bytes")
        self.limit = limit


class LocalMediaStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    @staticmethod
    def generate_key(extension: str, category: str = "videos") -> str:
        """A unique key such as ``videos/3f2c...9a.mp4``. The extension must be plain."""
        extension = extension.lower().lstrip(".")
        if not _EXTENSION_PATTERN.fullmatch(extension):
            raise InvalidStorageKey(f"Unsafe file extension: {extension!r}")
        return f"{category}/{uuid.uuid4().hex}.{extension}"

    def path_for(self, key: str) -> Path:
        """Absolute path for a key, guaranteed to be inside the media root."""
        if not _KEY_PATTERN.fullmatch(key) or ".." in key.split("/"):
            raise InvalidStorageKey(f"Invalid storage key: {key!r}")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise InvalidStorageKey(f"Storage key escapes the media root: {key!r}")
        return path

    def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def size(self, key: str) -> int:
        return self.path_for(key).stat().st_size

    def save(self, stream: BinaryIO, key: str, *, max_bytes: int | None = None) -> int:
        """Copy ``stream`` to ``key`` in chunks and return the byte count.

        The data goes to a temporary sibling first and is renamed into place at the
        end, so a reader never sees a half-written file and a failure (including
        exceeding ``max_bytes``) leaves nothing behind. Existing keys are never
        overwritten.
        """
        path = self.path_for(key)
        if path.exists():
            raise StorageError(f"Storage key already exists: {key!r}")
        path.parent.mkdir(parents=True, exist_ok=True)

        partial = path.with_name(f".{path.name}.part")
        written = 0
        try:
            with partial.open("wb") as target:
                while chunk := stream.read(CHUNK_SIZE):
                    written += len(chunk)
                    if max_bytes is not None and written > max_bytes:
                        raise FileTooLarge(max_bytes)
                    target.write(chunk)
            os.replace(partial, path)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return written

    def delete(self, key: str) -> None:
        """Remove the file if present. Deleting a missing key is not an error."""
        self.path_for(key).unlink(missing_ok=True)
