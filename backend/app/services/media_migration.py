"""Copy persistent media between storage backends, and verify a copy.

The database is the list of what must exist: every source video, audio asset, ready clip
and ready edit names its object by ``storage_key``. Migration is **copy-first and
resumable**: an object already present at the destination with the same size is skipped,
one with a *different* size is reported as a conflict and never overwritten, and nothing
is ever deleted from the source. Switch ``STORAGE_BACKEND`` only after ``verify`` passes;
the old copy stays until an operator removes it.
"""

import hashlib
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AudioAsset, Clip, ClipEdit, ClipEditStatus, ClipStatus, Video
from app.services.storage import (
    InvalidStorageKey,
    ObjectNotFound,
    StorageError,
    StorageProvider,
)


@dataclass(frozen=True)
class MediaObject:
    kind: str  # video | audio | clip | edit
    key: str


@dataclass
class Report:
    """What happened to each object. Keys only: never credentials or paths."""

    copied: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)  # already at the destination, same size
    missing_source: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # destination differs; not overwritten
    failed: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)  # verify: content differs
    bytes_copied: int = 0

    @property
    def ok(self) -> bool:
        return not (self.missing_source or self.conflicts or self.failed or self.mismatched)


def media_objects(db: Session) -> Iterator[MediaObject]:
    """Every object the database says must exist, in a stable order."""
    queries = (
        ("video", select(Video.storage_key)),
        ("audio", select(AudioAsset.storage_key)),
        ("clip", select(Clip.storage_key).where(Clip.status == ClipStatus.READY)),
        ("edit", select(ClipEdit.storage_key).where(ClipEdit.status == ClipEditStatus.READY)),
    )
    for kind, query in queries:
        for key in db.scalars(query.order_by(query.selected_columns[0])):
            if key:
                yield MediaObject(kind, key)


def _size(storage: StorageProvider, key: str) -> int | None:
    try:
        return storage.size(key)
    except ObjectNotFound:
        return None


def migrate(
    db: Session,
    source: StorageProvider,
    destination: StorageProvider,
    *,
    dry_run: bool = False,
    progress: Callable[[str, MediaObject], None] = lambda status, item: None,
) -> Report:
    """Copy every database-referenced object that the destination lacks."""
    report = Report()
    with tempfile.TemporaryDirectory(prefix="peaksift-migrate-") as tmp:
        work = Path(tmp)
        for item in media_objects(db):
            try:
                size = _size(source, item.key)
                if size is None:
                    report.missing_source.append(item.key)
                    progress("missing", item)
                    continue
                existing = _size(destination, item.key)
                if existing == size:
                    report.present.append(item.key)
                    progress("present", item)
                    continue
                if existing is not None:
                    report.conflicts.append(item.key)
                    progress("conflict", item)
                    continue
                if not dry_run:
                    local = source.fetch(item.key, work)
                    try:
                        destination.put_file(local, item.key)
                    finally:
                        if work in local.parents:
                            local.unlink(missing_ok=True)  # a download, not the stored file
                report.copied.append(item.key)
                report.bytes_copied += size
                progress("would copy" if dry_run else "copied", item)
            except (StorageError, OSError) as error:
                if isinstance(error, InvalidStorageKey):
                    report.missing_source.append(item.key)
                else:
                    report.failed.append(item.key)
                progress("failed", item)
    return report


def _digest(storage: StorageProvider, key: str, size: int) -> str:
    digest = hashlib.sha256()
    if size:
        for chunk in storage.iter_range(key, 0, size - 1):
            digest.update(chunk)
    return digest.hexdigest()


def verify(
    db: Session,
    source: StorageProvider,
    destination: StorageProvider,
    *,
    checksum: bool = False,
    progress: Callable[[str, MediaObject], None] = lambda status, item: None,
) -> Report:
    """Check that every database-referenced object is at the destination with the source's
    size (and, with ``checksum``, the same SHA-256 content)."""
    report = Report()
    for item in media_objects(db):
        try:
            size = _size(source, item.key)
            copied = _size(destination, item.key)
            if copied is None:
                report.failed.append(item.key)
                progress("absent", item)
            elif size is not None and copied != size:
                report.mismatched.append(item.key)
                progress("size differs", item)
            elif (
                checksum
                and size is not None
                and (_digest(source, item.key, size) != _digest(destination, item.key, copied))
            ):
                report.mismatched.append(item.key)
                progress("content differs", item)
            else:
                report.present.append(item.key)  # (a source gone since the copy is fine)
                progress("ok", item)
        except (StorageError, OSError):
            report.failed.append(item.key)
            progress("failed", item)
    return report
