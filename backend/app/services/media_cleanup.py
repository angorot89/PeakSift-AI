"""Finding and removing media nothing needs any more.

- **Orphans** are objects in media storage that no row refers to: left by a storage failure
  after a deletion, by a crash between storing an artifact and committing its row, or by
  older versions (normalized transcription audio, which is now scratch-only).
- **Stale scratch** is anything under ``WORK_ROOT`` older than the grace period: the
  workspace of a worker that died mid-job. Each worker host has its own scratch, so the
  command cleans the host it runs on.

Only objects and files **older than the grace period** are considered, and the grace period
can never be shorter than the longest a job may run, so an upload or render in progress is
never touched. Nothing is removed without ``apply``.
"""

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AudioAsset, Clip, ClipEdit, Transcription, Video
from app.services.clip_edit.storage import edit_storage_key
from app.services.clip_render.storage import clip_storage_key
from app.services.storage import LocalStorageProvider, StorageError, StorageProvider

# Categories of persistent media; ``transcription`` only holds legacy intermediates.
CATEGORIES = ("videos", "audio", "clips", "edits", "transcription")


@dataclass
class CleanupReport:
    orphans: list[tuple[str, int]] = field(default_factory=list)  # (key, size)
    partials: list[str] = field(default_factory=list)  # interrupted local writes
    scratch: list[str] = field(default_factory=list)  # stale scratch entries
    removed: int = 0
    failed: int = 0

    @property
    def orphan_bytes(self) -> int:
        return sum(size for _, size in self.orphans)


def referenced_keys(db: Session) -> set[str]:
    """Every key a row owns or may still produce (in-flight renders included)."""
    keys = set(db.scalars(select(Video.storage_key)))
    keys |= set(db.scalars(select(AudioAsset.storage_key)))
    for clip_id, key in db.execute(select(Clip.id, Clip.storage_key)):
        keys |= {clip_storage_key(clip_id), *([key] if key else [])}
    for edit_id, key in db.execute(select(ClipEdit.id, ClipEdit.storage_key)):
        keys |= {edit_storage_key(edit_id), *([key] if key else [])}
    return keys


def find_orphans(db: Session, storage: StorageProvider, cutoff: datetime) -> list[tuple[str, int]]:
    referenced = referenced_keys(db)
    return [
        (item.key, item.size)
        for category in CATEGORIES
        for item in storage.list_objects(category)
        if item.key not in referenced and item.modified < cutoff
    ]


def stale_scratch(root: Path, cutoff: datetime) -> list[Path]:
    """Top-level-to-leaf scratch entries whose every file is older than ``cutoff``: whole
    job directories (``<kind>/<id>/<attempt>``-style) and stray files."""
    if not root.is_dir():
        return []
    stale: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or any(path.is_relative_to(done) for done in stale):
            continue
        if path.is_file() and _mtime(path) < cutoff:
            stale.append(path)
        elif path.is_dir() and _all_older(path, cutoff) and any(path.iterdir()):
            stale.append(path)
    return stale


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _all_older(directory: Path, cutoff: datetime) -> bool:
    return _mtime(directory) < cutoff and all(
        _mtime(p) < cutoff for p in directory.rglob("*") if not p.is_symlink()
    )


def cleanup(
    db: Session,
    storage: StorageProvider,
    scratch_root: Path,
    *,
    grace: timedelta,
    apply: bool = False,
    now: datetime | None = None,
) -> CleanupReport:
    cutoff = (now or datetime.now(UTC)) - grace
    report = CleanupReport(orphans=find_orphans(db, storage, cutoff))
    partial_paths: list[Path] = []
    if isinstance(storage, LocalStorageProvider):
        partial_paths = [p for p, modified in storage.partial_files() if modified < cutoff]
        report.partials = [p.relative_to(storage.root).as_posix() for p in partial_paths]
    stale = stale_scratch(scratch_root, cutoff)
    report.scratch = [p.relative_to(scratch_root).as_posix() for p in stale]
    if not apply:
        return report

    for key, _ in report.orphans:
        try:
            storage.delete(key)
            report.removed += 1
        except StorageError:
            report.failed += 1
    legacy = [key for key, _ in report.orphans if key.startswith("transcription/")]
    if legacy:  # the column pointed at intermediates that no longer exist
        db.execute(
            update(Transcription)
            .where(Transcription.audio_storage_key.in_(legacy))
            .values(audio_storage_key=None)
        )
        db.commit()
    for path in [*partial_paths, *stale]:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            report.removed += 1
        except OSError:
            report.failed += 1
    return report
