"""The private visual asset domain: allow-listed kinds, metadata constraints per kind, duplicate
semantics within a project, unique storage keys, project cascade — and the storage references
every media tool must know (deletion, migration/backup inventory, orphan cleanup)."""

import io
import os
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Project, User, VisualAsset, VisualAssetKind
from app.services.media_cleanup import cleanup, referenced_keys
from app.services.media_deletion import delete_project, delete_visual_asset, project_media_keys
from app.services.media_migration import media_objects
from app.services.storage import LocalStorageProvider


def make_project(db: Session) -> Project:
    user = User(email=f"creator-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    project = Project(name="Space explainer", owner=user)
    db.add_all([user, project])
    db.flush()
    return project


def image_fields(project: Project, **overrides) -> dict:
    fields = {
        "project": project,
        "kind": VisualAssetKind.IMAGE,
        "display_name": "moon.png",
        "storage_key": f"visuals/{uuid.uuid4().hex}.png",
        "content_type": "image/png",
        "file_size": 2048,
        "sha256": uuid.uuid4().hex * 2,
        "width": 1600,
        "height": 900,
        "codec": "png",
        "container": "png",
        "has_alpha": True,
        "thumbnail_storage_key": f"visuals/{uuid.uuid4().hex}.png",
    }
    fields.update(overrides)
    return fields


def video_fields(project: Project, **overrides) -> dict:
    fields = image_fields(
        project,
        kind=VisualAssetKind.VIDEO,
        display_name="launch.mp4",
        storage_key=f"visuals/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        width=1080,
        height=1920,
        duration_seconds=8.5,
        fps=29.97,
        codec="h264",
        container="mp4",
        has_alpha=False,
        has_audio=True,
        thumbnail_storage_key=f"visuals/{uuid.uuid4().hex}.jpg",
    )
    fields.update(overrides)
    return fields


def make_asset(db: Session, fields: dict) -> VisualAsset:
    asset = VisualAsset(**fields)
    db.add(asset)
    db.flush()
    return asset


def test_valid_image_and_video_assets_are_stored_with_their_metadata(db_session):
    project = make_project(db_session)
    image = make_asset(db_session, image_fields(project))
    video = make_asset(db_session, video_fields(project))
    db_session.commit()
    stored = db_session.get(VisualAsset, image.id)
    assert stored.kind == "image" and stored.duration_seconds is None and stored.has_alpha
    stored = db_session.get(VisualAsset, video.id)
    assert (stored.width, stored.height, stored.duration_seconds) == (1080, 1920, 8.5)
    assert stored.created_at is not None and stored.updated_at is not None
    assert {a.id for a in project.visual_assets} == {image.id, video.id}


def test_kinds_are_an_allow_list():
    assert {k.value for k in VisualAssetKind} == {"image", "video"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "gif"},
        {"display_name": ""},
        {"file_size": 0},
        {"width": 0},
        {"height": -4},
        {"sha256": "abc"},
        {"duration_seconds": 3.0},  # an image has no duration
        {"fps": 30.0},  # nor a frame rate
        {"has_audio": True},  # nor sound
    ],
)
def test_image_constraints_refuse_invalid_rows(db_session, overrides):
    project = make_project(db_session)
    with pytest.raises(IntegrityError):
        make_asset(db_session, image_fields(project, **overrides))
    db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_seconds": None},  # a video always has a duration
        {"duration_seconds": 0.0},
        {"fps": 0.0},
        {"has_alpha": True},  # transparency is an image-only property here
    ],
)
def test_video_constraints_refuse_invalid_rows(db_session, overrides):
    project = make_project(db_session)
    with pytest.raises(IntegrityError):
        make_asset(db_session, video_fields(project, **overrides))
    db_session.rollback()


def test_a_video_without_a_known_frame_rate_or_thumbnail_is_allowed(db_session):
    project = make_project(db_session)
    make_asset(db_session, video_fields(project, fps=None, thumbnail_storage_key=None))
    db_session.commit()


def test_the_same_file_is_one_asset_per_project(db_session):
    project, other = make_project(db_session), make_project(db_session)
    digest = "b" * 64
    make_asset(db_session, image_fields(project, sha256=digest))
    make_asset(db_session, image_fields(other, sha256=digest))  # another project never collides
    db_session.commit()
    with pytest.raises(IntegrityError):
        make_asset(db_session, image_fields(project, sha256=digest))
    db_session.rollback()


@pytest.mark.parametrize("column", ["storage_key", "thumbnail_storage_key"])
def test_storage_keys_are_unique(db_session, column):
    project = make_project(db_session)
    key = f"visuals/{uuid.uuid4().hex}.png"
    make_asset(db_session, image_fields(project, **{column: key}))
    with pytest.raises(IntegrityError):
        make_asset(db_session, image_fields(project, **{column: key}))
    db_session.rollback()


def test_deleting_a_project_deletes_its_assets_in_the_database(db_session):
    project = make_project(db_session)
    asset_id = make_asset(db_session, image_fields(project)).id
    db_session.commit()
    db_session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project.id})
    db_session.commit()
    db_session.expire_all()
    assert db_session.scalar(select(VisualAsset).where(VisualAsset.id == asset_id)) is None


# --- storage references -----------------------------------------------------------------------


@pytest.fixture
def local(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "media")


def stored_asset(db: Session, storage: LocalStorageProvider, project: Project) -> VisualAsset:
    """A video asset whose file and thumbnail really exist in ``storage``."""
    key = storage.generate_key("mp4", category="visuals")
    thumbnail = storage.generate_key("jpg", category="visuals")
    storage.save(io.BytesIO(b"video bytes"), key)
    storage.save(io.BytesIO(b"thumbnail bytes"), thumbnail)
    asset = make_asset(db, video_fields(project, storage_key=key, thumbnail_storage_key=thumbnail))
    db.commit()
    return asset


def test_every_media_tool_knows_an_asset_and_its_thumbnail(db_session, local):
    project = make_project(db_session)
    asset = stored_asset(db_session, local, project)
    owned = {asset.storage_key, asset.thumbnail_storage_key}
    assert owned <= project_media_keys(db_session, project)
    assert owned <= referenced_keys(db_session)
    inventory = {(item.kind, item.key) for item in media_objects(db_session)}
    assert ("visual", asset.storage_key) in inventory
    assert ("thumbnail", asset.thumbnail_storage_key) in inventory


def test_deleting_an_asset_removes_its_row_then_both_objects(db_session, local):
    asset = stored_asset(db_session, local, make_project(db_session))
    keys = asset.storage_keys
    report = delete_visual_asset(db_session, local, asset)
    assert (report.deleted, report.failed) == (2, 0)
    assert not any(local.exists(key) for key in keys)
    assert db_session.scalar(select(VisualAsset)) is None


def test_deleting_a_project_removes_its_visual_files(db_session, local):
    project = make_project(db_session)
    keys = stored_asset(db_session, local, project).storage_keys
    delete_project(db_session, local, project)
    assert not any(local.exists(key) for key in keys)


def test_cleanup_finds_old_unreferenced_visual_files_and_spares_referenced_ones(
    db_session, local, tmp_path
):
    asset = stored_asset(db_session, local, make_project(db_session))
    orphan = local.generate_key("png", category="visuals")
    local.save(io.BytesIO(b"left behind"), orphan)
    stamp = time.time() - 72 * 3600
    for key in (orphan, *asset.storage_keys):
        os.utime(local.path_for(key), (stamp, stamp))

    report = cleanup(db_session, local, tmp_path / "work", grace=timedelta(hours=24), apply=True)

    assert [key for key, _ in report.orphans] == [orphan]
    assert not local.exists(orphan)
    assert all(local.exists(key) for key in asset.storage_keys)
