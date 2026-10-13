"""Where rendered clips live and how they become final.

Layout under ``MEDIA_ROOT`` (keys are application-generated; titles, filenames, project
or user names never become paths)::

    clips/<clip-uuid>/clip-tmp.mp4   # being rendered / validated
    clips/<clip-uuid>/clip.mp4       # the final, validated artifact

A render writes the temporary file, validation inspects it, and only then is it renamed
atomically to the final name. A reader can therefore never see a half-written final
artifact, and a failed render is discarded without leaving a corrupt ``clip.mp4``.
"""

import os
import re
import unicodedata
import uuid
from pathlib import Path

from app.services.storage import LocalMediaStorage, StorageError

FINAL_NAME = "clip.mp4"
TEMP_NAME = "clip-tmp.mp4"


class ArtifactExists(StorageError):
    """A final artifact is already in place; it must be discarded explicitly first."""


class ArtifactMissing(StorageError):
    """The temporary artifact to finalize is absent or empty."""


def _clip_id(value: uuid.UUID | str) -> str:
    """Only a real UUID may name a clip directory (anything else cannot be a key)."""
    return str(uuid.UUID(str(value)))


def clip_storage_key(clip_id: uuid.UUID | str) -> str:
    return f"clips/{_clip_id(clip_id)}/{FINAL_NAME}"


def clip_temp_key(clip_id: uuid.UUID | str) -> str:
    return f"clips/{_clip_id(clip_id)}/{TEMP_NAME}"


class ClipArtifactStore:
    """The few operations the renderer and pipeline need, all resolved through
    ``LocalMediaStorage.path_for`` so nothing can escape the media root."""

    def __init__(self, storage: LocalMediaStorage) -> None:
        self.storage = storage

    def temp_path(self, clip_id: uuid.UUID | str) -> Path:
        """Where the renderer should write; the directory is created, stale temp removed."""
        path = self.storage.path_for(clip_temp_key(clip_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        return path

    def final_path(self, clip_id: uuid.UUID | str) -> Path:
        return self.storage.path_for(clip_storage_key(clip_id))

    def exists(self, clip_id: uuid.UUID | str) -> bool:
        path = self.final_path(clip_id)
        return path.is_file() and path.stat().st_size > 0

    def finalize(self, clip_id: uuid.UUID | str) -> str:
        """Atomically promote the validated temp file to the final artifact; return its key."""
        temp, final = self.storage.path_for(clip_temp_key(clip_id)), self.final_path(clip_id)
        if not temp.is_file() or temp.stat().st_size == 0:
            raise ArtifactMissing("There is no rendered output to finalize")
        if final.exists():
            raise ArtifactExists("A final clip artifact already exists")
        os.replace(temp, final)  # same directory: atomic on POSIX
        return clip_storage_key(clip_id)

    def discard(self, clip_id: uuid.UUID | str) -> None:
        """Remove temp and final artifacts (and the now-empty directory). Idempotent."""
        temp, final = self.storage.path_for(clip_temp_key(clip_id)), self.final_path(clip_id)
        temp.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        try:
            temp.parent.rmdir()
        except OSError:
            pass  # not empty or already gone

    def discard_temp(self, clip_id: uuid.UUID | str) -> None:
        self.storage.path_for(clip_temp_key(clip_id)).unlink(missing_ok=True)


# --- download names -----------------------------------------------------------------------------

_SLUG_MAX = 60
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def safe_download_filename(title: str | None, clip_id: uuid.UUID | str) -> str:
    """``that-was-crazy-3f2c9a.mp4``: an ASCII slug of the title plus a short id.

    The title only ever influences the *download* name shown to the browser; the storage
    path is always the generated key. Unicode is transliterated where possible and
    dropped otherwise; slashes, quotes, control characters and length are neutralised.
    """
    normalised = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    slug = _NON_SLUG.sub("-", normalised.lower()).strip("-")[:_SLUG_MAX].strip("-") or "clip"
    return f"{slug}-{_clip_id(clip_id)[:8]}.mp4"
