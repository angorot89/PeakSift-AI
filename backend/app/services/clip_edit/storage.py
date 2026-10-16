"""Private storage for edited shorts.

Layout (keys are generated; titles and user input never become keys)::

    edits/<edit-uuid>/work-<attempt>/captions.ass   # scratch (WORK_ROOT): this attempt's captions
    edits/<edit-uuid>/work-<attempt>/short.mp4      # scratch: this attempt's render, in validation
    edits/<edit-uuid>/edited.mp4                    # media storage: the final, validated artifact

Each attempt works in its own scratch directory, so a stalled worker that a retry fenced out
can never write into, finalize from, or clean up the newer attempt's files. The validated
render is stored under ``edited.mp4`` through the storage contract (local directory or
private bucket), which never overwrites and is all-or-nothing: a reader never sees a
partial file.
"""

import shutil
import uuid
from pathlib import Path

from app.services.clip_edit.composition import CAPTIONS_FILENAME
from app.services.storage import (
    LocalStorageProvider,
    ObjectNotFound,
    StorageError,
    StorageProvider,
)

FINAL_NAME = "edited.mp4"
WORK_RENDER_NAME = "short.mp4"


class EditArtifactMissing(StorageError):
    """The attempt's render to finalize is absent or empty."""


class EditArtifactExists(StorageError):
    """A final artifact is already in place; it must be discarded explicitly first."""


def _edit_id(value: uuid.UUID | str) -> str:
    return str(uuid.UUID(str(value)))


def _attempt(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("attempt must be a positive integer")
    return value


def edit_directory_key(edit_id: uuid.UUID | str) -> str:
    return f"edits/{_edit_id(edit_id)}"


def edit_storage_key(edit_id: uuid.UUID | str) -> str:
    return f"{edit_directory_key(edit_id)}/{FINAL_NAME}"


def workspace_key(edit_id: uuid.UUID | str, attempt: int) -> str:
    return f"{edit_directory_key(edit_id)}/work-{_attempt(attempt)}"


class EditArtifactStore:
    """Attempt workspaces in the local scratch area; final shorts through the contract."""

    def __init__(
        self, storage: StorageProvider, scratch: LocalStorageProvider | None = None
    ) -> None:
        from app.core.config import get_settings
        from app.services.workspace import scratch_storage

        self.storage = storage
        self.scratch = scratch or scratch_storage(get_settings())

    def workspace(self, edit_id: uuid.UUID | str, attempt: int) -> Path:
        """A fresh, empty directory for this attempt (leftovers from a crash are removed)."""
        path = self.scratch.path_for(workspace_key(edit_id, attempt))
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def captions_path(self, edit_id: uuid.UUID | str, attempt: int) -> Path:
        return self.scratch.path_for(f"{workspace_key(edit_id, attempt)}/captions.ass")

    def render_path(self, edit_id: uuid.UUID | str, attempt: int) -> Path:
        return self.scratch.path_for(f"{workspace_key(edit_id, attempt)}/{WORK_RENDER_NAME}")

    def exists(self, edit_id: uuid.UUID | str) -> bool:
        try:
            return self.storage.size(edit_storage_key(edit_id)) > 0
        except ObjectNotFound:
            return False

    def finalize(self, edit_id: uuid.UUID | str, attempt: int) -> str:
        """Store this attempt's validated render as the final short; return the final key."""
        render, key = self.render_path(edit_id, attempt), edit_storage_key(edit_id)
        if not render.is_file() or render.stat().st_size == 0:
            raise EditArtifactMissing("There is no rendered short to finalize")
        if self.storage.exists(key):
            raise EditArtifactExists("A final edited artifact already exists")
        self.storage.put_file(render, key)  # never overwrites; all-or-nothing
        render.unlink(missing_ok=True)
        return key

    def discard_workspace(self, edit_id: uuid.UUID | str, attempt: int) -> None:
        """Remove only this attempt's directory (captions file and temp render)."""
        path = self.scratch.path_for(workspace_key(edit_id, attempt))
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)

    def discard(self, edit_id: uuid.UUID | str) -> None:
        """Remove every attempt's workspace and the final artifact. Idempotent."""
        directory = self.scratch.path_for(edit_directory_key(edit_id))
        if directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory, ignore_errors=True)
        self.storage.delete(edit_storage_key(edit_id))


__all__ = [
    "CAPTIONS_FILENAME",
    "EditArtifactExists",
    "EditArtifactMissing",
    "EditArtifactStore",
    "edit_storage_key",
    "workspace_key",
]
