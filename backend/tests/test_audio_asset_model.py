"""The private audio asset domain: allow-listed kinds, metadata constraints, duplicate
semantics within a project, storage-key uniqueness and project cascade."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AudioAsset, AudioAssetKind, Project, User


def make_project(db: Session) -> Project:
    user = User(email=f"creator-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    project = Project(name="Podcast", owner=user)
    db.add_all([user, project])
    db.flush()
    return project


def make_asset(db: Session, project: Project, **overrides) -> AudioAsset:
    fields = {
        "project": project,
        "kind": AudioAssetKind.MUSIC,
        "display_name": "Night drive.mp3",
        "storage_key": f"audio/{uuid.uuid4().hex}.mp3",
        "content_type": "audio/mpeg",
        "file_size": 1024,
        "sha256": uuid.uuid4().hex * 2,
        "container": "mp3",
        "codec": "mp3",
        "duration_seconds": 182.4,
        "sample_rate": 44100,
        "channels": 2,
        "waveform_peaks": [0, 12, 80, 100, 40],
    }
    fields.update(overrides)
    asset = AudioAsset(**fields)
    db.add(asset)
    db.flush()
    return asset


def test_a_valid_asset_is_stored_with_its_metadata(db_session):
    project = make_project(db_session)
    asset = make_asset(db_session, project)
    db_session.commit()
    stored = db_session.get(AudioAsset, asset.id)
    assert stored.kind == "music" and stored.project_id == project.id
    assert stored.waveform_peaks == [0, 12, 80, 100, 40]
    assert stored.created_at is not None and stored.updated_at is not None
    assert [a.id for a in project.audio_assets] == [asset.id]


def test_kinds_are_an_allow_list():
    assert {k.value for k in AudioAssetKind} == {"music", "sfx"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "podcast"},
        {"display_name": ""},
        {"file_size": 0},
        {"duration_seconds": 0.0},
        {"duration_seconds": -1.0},
        {"sample_rate": 0},
        {"channels": 0},
        {"sha256": "abc"},
        {"waveform_peaks": {"peaks": []}},
    ],
)
def test_constraints_refuse_invalid_rows(db_session, overrides):
    project = make_project(db_session)
    with pytest.raises(IntegrityError):
        make_asset(db_session, project, **overrides)
    db_session.rollback()


def test_the_same_file_for_the_same_purpose_is_one_asset_per_project(db_session):
    project, other = make_project(db_session), make_project(db_session)
    digest = "a" * 64
    make_asset(db_session, project, sha256=digest)
    make_asset(db_session, project, sha256=digest, kind=AudioAssetKind.SFX)  # another purpose
    make_asset(db_session, other, sha256=digest)  # another project never collides
    db_session.commit()
    with pytest.raises(IntegrityError):
        make_asset(db_session, project, sha256=digest)
    db_session.rollback()


def test_storage_keys_are_unique(db_session):
    project = make_project(db_session)
    key = f"audio/{uuid.uuid4().hex}.wav"
    make_asset(db_session, project, storage_key=key)
    with pytest.raises(IntegrityError):
        make_asset(db_session, project, storage_key=key)
    db_session.rollback()


def test_deleting_a_project_deletes_its_assets_in_the_database(db_session):
    project = make_project(db_session)
    asset_id = make_asset(db_session, project).id
    db_session.commit()
    db_session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project.id})
    db_session.commit()
    db_session.expire_all()
    assert db_session.scalar(select(AudioAsset).where(AudioAsset.id == asset_id)) is None
