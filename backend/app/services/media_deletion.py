"""Deleting media together with the rows that own it.

The rule is **rows first, objects second**: the storage keys are captured, the rows are
deleted in one commit, and only then are the objects removed. A failure before the commit
deletes nothing; a storage failure afterwards leaves *orphans* — objects no row refers to —
which are counted (never hidden) and removed later by ``python -m app.cli.media cleanup``.
A render still running for a deleted row notices the row is gone and discards its own
output.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AudioAsset, Clip, ClipEdit, Project, Video
from app.services.clip_edit.storage import edit_storage_key
from app.services.clip_render.storage import clip_storage_key
from app.services.storage import StorageError, StorageProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeletionReport:
    deleted: int  # objects removed (or already absent)
    failed: int  # objects left behind for the cleanup command


def project_media_keys(db: Session, project: Project) -> set[str]:
    """Every object the project's rows own or may still produce (an in-flight render's
    deterministic final key included)."""
    keys = set(db.scalars(select(Video.storage_key).where(Video.project_id == project.id)))
    keys |= set(
        db.scalars(select(AudioAsset.storage_key).where(AudioAsset.project_id == project.id))
    )
    video_ids = select(Video.id).where(Video.project_id == project.id)
    for clip_id, key in db.execute(
        select(Clip.id, Clip.storage_key).where(Clip.video_id.in_(video_ids))
    ):
        keys |= {clip_storage_key(clip_id), *([key] if key else [])}
    for edit_id, key in db.execute(
        select(ClipEdit.id, ClipEdit.storage_key).where(ClipEdit.video_id.in_(video_ids))
    ):
        keys |= {edit_storage_key(edit_id), *([key] if key else [])}
    return keys


def delete_objects(storage: StorageProvider, keys: Iterable[str]) -> DeletionReport:
    """Remove each object (absent ones count as removed). Failures are counted, not raised."""
    deleted = failed = 0
    for key in sorted(set(keys)):
        try:
            storage.delete(key)
            deleted += 1
        except StorageError:
            failed += 1
    if failed:
        logger.error("%s media objects could not be deleted; cleanup will remove them", failed)
    return DeletionReport(deleted, failed)


def delete_project(db: Session, storage: StorageProvider, project: Project) -> DeletionReport:
    keys = project_media_keys(db, project)  # captured before the rows disappear
    db.delete(project)
    db.commit()
    return delete_objects(storage, keys)


def edits_using_asset(db: Session, asset: AudioAsset) -> int:
    """How many of the project's edits reference ``asset`` in their audio section."""
    wanted = str(asset.id)
    configs = db.scalars(
        select(ClipEdit.config)
        .join(Video, ClipEdit.video_id == Video.id)
        .where(Video.project_id == asset.project_id)
    )
    return sum(1 for config in configs if wanted in _asset_ids(config))


def _asset_ids(config: dict | None) -> set[str]:
    audio = (config or {}).get("audio") or {}
    ids = {((audio.get("music") or {}).get("asset_id"))}
    ids |= {(cue or {}).get("asset_id") for cue in audio.get("sfx") or []}
    return {str(i) for i in ids if i}


def delete_audio_asset(db: Session, storage: StorageProvider, asset: AudioAsset) -> DeletionReport:
    key = asset.storage_key
    db.delete(asset)
    db.commit()
    return delete_objects(storage, [key])


def delete_edit(db: Session, storage: StorageProvider, edit: ClipEdit) -> DeletionReport:
    keys = {edit_storage_key(edit.id), *([edit.storage_key] if edit.storage_key else [])}
    db.delete(edit)
    db.commit()
    return delete_objects(storage, keys)


__all__ = [
    "DeletionReport",
    "delete_audio_asset",
    "delete_edit",
    "delete_objects",
    "delete_project",
    "edits_using_asset",
    "project_media_keys",
]
