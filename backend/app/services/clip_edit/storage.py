"""Private storage for edited shorts.

Layout under ``MEDIA_ROOT`` (keys are generated; titles and user input never become paths)::

    edits/<edit-uuid>/work-<attempt>/captions.ass   # this attempt's caption file
    edits/<edit-uuid>/work-<attempt>/short.mp4      # this attempt's render, being validated
    edits/<edit-uuid>/edited.mp4                    # the final, validated artifact

Each attempt works in its own directory, so a stalled worker that a retry fenced out can
never write into, finalize from, or clean up the newer attempt's files. The validated render
is moved to ``edited.mp4`` with an atomic rename; a reader never sees a partial file.
"""

import os
import shutil
import uuid
from pathlib import Path

from app.services.clip_edit.composition import CAPTIONS_FILENAME
from app.services.storage import LocalMediaStorage, StorageError

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
    def __init__(self, storage: LocalMediaStorage) -> None:
        self.storage = storage

    def workspace(self, edit_id: uuid.UUID | str, attempt: int) -> Path:
        """A fresh, empty directory for this attempt (leftovers from a crash are removed)."""
        path = self.storage.path_for(workspace_key(edit_id, attempt))
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def captions_path(self, edit_id: uuid.UUID | str, attempt: int) -> Path:
        return self.storage.path_for(f"{workspace_key(edit_id, attempt)}/captions.ass")

    def render_path(self, edit_id: uuid.UUID | str, attempt: int) -> Path:
        return self.storage.path_for(f"{workspace_key(edit_id, attempt)}/{WORK_RENDER_NAME}")

    def final_path(self, edit_id: uuid.UUID | str) -> Path:
        return self.storage.path_for(edit_storage_key(edit_id))

    def exists(self, edit_id: uuid.UUID | str) -> bool:
        path = self.final_path(edit_id)
        return path.is_file() and path.stat().st_size > 0

    def finalize(self, edit_id: uuid.UUID | str, attempt: int) -> str:
        """Atomically promote this attempt's validated render; return the final key."""
        render, final = self.render_path(edit_id, attempt), self.final_path(edit_id)
        if not render.is_file() or render.stat().st_size == 0:
            raise EditArtifactMissing("There is no rendered short to finalize")
        if final.exists():
            raise EditArtifactExists("A final edited artifact already exists")
        os.replace(render, final)  # same filesystem (both under MEDIA_ROOT): atomic
        return edit_storage_key(edit_id)

    def discard_workspace(self, edit_id: uuid.UUID | str, attempt: int) -> None:
        """Remove only this attempt's directory (captions file and temp render)."""
        path = self.storage.path_for(workspace_key(edit_id, attempt))
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)

    def discard(self, edit_id: uuid.UUID | str) -> None:
        """Remove every attempt's workspace and the final artifact. Idempotent."""
        directory = self.storage.path_for(edit_directory_key(edit_id))
        if directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory, ignore_errors=True)


__all__ = [
    "CAPTIONS_FILENAME",
    "EditArtifactExists",
    "EditArtifactMissing",
    "EditArtifactStore",
    "edit_storage_key",
    "workspace_key",
]
