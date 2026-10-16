"""Local scratch space for media work.

FFmpeg, ffprobe and the speech and face models read and write local files, while persistent
media lives behind the storage contract (possibly in a remote bucket). So every job works in
its own directory under ``WORK_ROOT``: inputs are fetched there (or read in place from local
storage), intermediates and renders are written and validated there, and only finished
artifacts are stored. Nothing in it is ever served, and each attempt owns its own directory,
so a stalled worker that a retry fenced out can never touch the newer attempt's files.
"""

import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.config import Settings
from app.services.storage import LocalStorageProvider


def work_root(settings: Settings) -> Path:
    """The scratch root, created owner-only (it holds private media while jobs run, and the
    default lives in the shared system temp directory)."""
    root = Path(settings.work_root or Path(tempfile.gettempdir()) / "peaksift-work")
    if not root.is_dir():
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def scratch_storage(settings: Settings) -> LocalStorageProvider:
    """Key-addressed scratch files under ``WORK_ROOT`` (same key rules as media storage)."""
    return LocalStorageProvider(work_root(settings))


def attempt_tag(task_id: str | None) -> str:
    """A path-safe name for one attempt, derived from its task id (the fencing token)."""
    return "".join(ch for ch in (task_id or "inline") if ch.isalnum())[:16] or "inline"


@contextmanager
def job_workspace(
    settings: Settings, kind: str, job_id: uuid.UUID | str, task_id: str | None
) -> Iterator[Path]:
    """A fresh directory for one attempt of one job, removed when the block ends."""
    key = f"{kind}/{uuid.UUID(str(job_id))}/{attempt_tag(task_id)}"
    path = scratch_storage(settings).path_for(key)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)  # leftovers of a crashed run of this same attempt
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def scratch_directory(settings: Settings, purpose: str) -> Iterator[Path]:
    """A private temporary directory under ``WORK_ROOT/<purpose>`` (e.g. an upload being
    validated), removed when the block ends."""
    parent = work_root(settings) / purpose
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        yield Path(directory)
