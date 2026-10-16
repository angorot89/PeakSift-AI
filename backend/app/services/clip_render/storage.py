"""Where rendered clips live and how they become final.

Layout (keys are application-generated; titles, filenames, project or user names never
become keys)::

    clips/<clip-uuid>/clip-tmp-<attempt>.mp4   # scratch (WORK_ROOT): rendered and validated
    clips/<clip-uuid>/clip.mp4                 # media storage: the final, validated artifact

A render writes its attempt's temporary file in the local scratch area, validation
inspects it, and only then is it stored under the final key through the storage contract
(local directory or private bucket). Storing never overwrites and is all-or-nothing, so a
reader can never see a half-written final artifact, and a failed render is discarded
without leaving a corrupt ``clip.mp4``.

Each attempt writes its own temp file, so a stalled worker that a retry has fenced out can
never write into, or clean up, the file the new attempt is producing.
"""

import re
import unicodedata
import uuid
from pathlib import Path

from app.services.storage import (
    LocalStorageProvider,
    ObjectNotFound,
    StorageError,
    StorageProvider,
)

FINAL_NAME = "clip.mp4"
TEMP_PREFIX = "clip-tmp-"


class ArtifactExists(StorageError):
    """A final artifact is already in place; it must be discarded explicitly first."""


class ArtifactMissing(StorageError):
    """The temporary artifact to finalize is absent or empty."""


def _clip_id(value: uuid.UUID | str) -> str:
    """Only a real UUID may name a clip directory (anything else cannot be a key)."""
    return str(uuid.UUID(str(value)))


def clip_storage_key(clip_id: uuid.UUID | str) -> str:
    return f"clips/{_clip_id(clip_id)}/{FINAL_NAME}"


def clip_temp_key(clip_id: uuid.UUID | str, attempt: int = 1) -> str:
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    return f"clips/{_clip_id(clip_id)}/{TEMP_PREFIX}{attempt}.mp4"


def clip_directory_key(clip_id: uuid.UUID | str) -> str:
    return f"clips/{_clip_id(clip_id)}"


class ClipArtifactStore:
    """The few operations the renderer and pipeline need: temp files in the local scratch
    area, final artifacts through the storage contract."""

    def __init__(
        self, storage: StorageProvider, scratch: LocalStorageProvider | None = None
    ) -> None:
        from app.core.config import get_settings
        from app.services.workspace import scratch_storage

        self.storage = storage
        self.scratch = scratch or scratch_storage(get_settings())

    def temp_path(self, clip_id: uuid.UUID | str, attempt: int = 1) -> Path:
        """Where this attempt's renderer writes; the directory is created, stale temp removed."""
        path = self.scratch.path_for(clip_temp_key(clip_id, attempt))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        return path

    def exists(self, clip_id: uuid.UUID | str) -> bool:
        try:
            return self.storage.size(clip_storage_key(clip_id)) > 0
        except ObjectNotFound:
            return False

    def finalize(self, clip_id: uuid.UUID | str, attempt: int = 1) -> str:
        """Store this attempt's validated temp file as the final artifact; return its key."""
        temp = self.scratch.path_for(clip_temp_key(clip_id, attempt))
        key = clip_storage_key(clip_id)
        if not temp.is_file() or temp.stat().st_size == 0:
            raise ArtifactMissing("There is no rendered output to finalize")
        if self.storage.exists(key):
            raise ArtifactExists("A final clip artifact already exists")
        self.storage.put_file(temp, key)  # never overwrites; all-or-nothing
        temp.unlink(missing_ok=True)
        return key

    def discard(self, clip_id: uuid.UUID | str) -> None:
        """Remove every temp file and the final artifact. Idempotent."""
        directory = self.scratch.path_for(clip_directory_key(clip_id))
        if directory.is_dir():
            for temp in directory.glob(f"{TEMP_PREFIX}*.mp4"):
                temp.unlink(missing_ok=True)
            try:
                directory.rmdir()
            except OSError:
                pass  # not empty or already gone
        self.storage.delete(clip_storage_key(clip_id))

    def discard_temp(self, clip_id: uuid.UUID | str, attempt: int = 1) -> None:
        """Remove only this attempt's temp file (never another attempt's output)."""
        self.scratch.path_for(clip_temp_key(clip_id, attempt)).unlink(missing_ok=True)


# --- download names -----------------------------------------------------------------------------

_SLUG_MAX = 60
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def safe_download_filename(
    title: str | None, clip_id: uuid.UUID | str, *, variant: str | None = None
) -> str:
    """``that-was-crazy-3f2c9a.mp4``: an ASCII slug of the title plus a short id
    (``that-was-crazy-vertical-3f2c9a.mp4`` with ``variant="vertical"``).

    The title only ever influences the *download* name shown to the browser; the storage
    path is always the generated key. Unicode is transliterated where possible and
    dropped otherwise; slashes, quotes, control characters and length are neutralised.
    """
    normalised = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    slug = _NON_SLUG.sub("-", normalised.lower()).strip("-")[:_SLUG_MAX].strip("-") or "clip"
    if variant is not None:
        tag = _NON_SLUG.sub("-", variant.lower()).strip("-")[:16]
        if tag:
            slug = f"{slug}-{tag}"
    return f"{slug}-{_clip_id(clip_id)[:8]}.mp4"
