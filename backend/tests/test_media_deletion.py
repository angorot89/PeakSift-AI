"""Deleting projects, audio and edits removes their media; leftovers are cleaned up.

Rows go first (one commit), objects second; a storage failure leaves counted orphans that
``cleanup`` removes. Nothing young, referenced or belonging to someone else is touched.
"""

import io
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import clip_edits as edits_api
from app.api.deps import get_storage
from app.cli import media as cli
from app.main import app
from app.models import (
    AudioAsset,
    AudioAssetKind,
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    Project,
    Transcription,
    TranscriptSegment,
    User,
    Video,
)
from app.services.clip_edit.storage import edit_storage_key
from app.services.clip_render import pipeline as render_pipeline
from app.services.clip_render.storage import ClipArtifactStore, clip_storage_key
from app.services.media_cleanup import cleanup
from app.services.storage import LocalStorageProvider, StorageUnavailable

PASSWORD = "correct horse battery"
OLD = timedelta(hours=48)


@pytest.fixture
def storage(tmp_path: Path, monkeypatch) -> LocalStorageProvider:
    local = LocalStorageProvider(tmp_path / "media")
    app.dependency_overrides[get_storage] = lambda: local
    monkeypatch.setattr(edits_api, "enqueue_clip_edit", lambda edit_id, *, task_id: task_id)
    monkeypatch.setattr(edits_api, "supports_captions", lambda path: True)
    yield local
    app.dependency_overrides.pop(get_storage, None)


def sign_up(client: TestClient, email: str) -> User:
    client.cookies.clear()
    assert client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
    return email


def put(storage: LocalStorageProvider, key: str, data: bytes = b"media") -> str:
    storage.save(io.BytesIO(data), key)
    return key


def library(db: Session, storage: LocalStorageProvider, email: str) -> dict:
    """A project with a video, a music asset, a ready clip and its objects."""
    user = db.scalar(select(User).where(User.email == email))
    project = Project(name="My Stream", owner=user)
    video = Video(project=project, original_filename="s.mp4", content_type="video/mp4",
                  storage_key=put(storage, storage.generate_key("mp4")), file_size=5,
                  status="ready", duration_seconds=60.0)  # fmt: skip
    music = AudioAsset(
        project=project, kind=AudioAssetKind.MUSIC, display_name="m.mp3", content_type="audio/mpeg",
        storage_key=put(storage, storage.generate_key("mp3", category="audio")), file_size=5,
        sha256=uuid.uuid4().hex * 2, container="mp3", codec="mp3", duration_seconds=30.0,
        sample_rate=44100, channels=2, waveform_peaks=[1, 2],
    )  # fmt: skip
    transcription = Transcription(video=video, provider="f", model="f", status="completed")
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0.0, end_time=20.0, text="hello")
    )
    run = ClipDetectionRun(
        video=video, transcription=transcription, transcript_fingerprint="f" * 64,
        provider="o", model="m", config={}, status="completed",
    )  # fmt: skip
    db.add_all([project, video, music, transcription, run])
    db.flush()
    candidate = ClipCandidate(
        run=run, video_id=video.id, start_time=0.0, end_time=20.0, duration_seconds=20.0,
        title="t", hook="h", rationale="r", category="story", transcript_excerpt="x",
        overall_score=80, hook_score=80, entertainment_score=80, clarity_score=80,
        payoff_score=80, completeness_score=80, rank=1,
    )  # fmt: skip
    clip = Clip(candidate=candidate, video_id=video.id, start_time=0.0, end_time=20.0,
                duration_seconds=20.0, status="ready", audio_codec="aac")  # fmt: skip
    db.add_all([candidate, clip])
    db.flush()
    clip.storage_key = put(storage, clip_storage_key(clip.id))
    db.commit()
    edits = f"/projects/{project.id}/videos/{video.id}/clips/{clip.id}/edits"
    return {"project": project, "video": video, "music": music, "clip": clip, "edits": edits}


def ready_edit(client: TestClient, db: Session, storage, lib: dict, body: dict) -> ClipEdit:
    response = client.post(lib["edits"], json=body)
    assert response.status_code == 201, response.text
    edit = db.get(ClipEdit, uuid.UUID(response.json()["id"]))
    edit.storage_key = put(storage, edit_storage_key(edit.id))
    edit.status = "ready"
    db.commit()
    return edit


def objects(storage: LocalStorageProvider) -> set[str]:
    return {
        item.key
        for category in ("videos", "audio", "clips", "edits")
        for item in storage.list_objects(category)
    }


# --- projects -----


def test_project_deletion_needs_the_exact_name(client, db_session, storage):
    lib = library(db_session, storage, sign_up(client, "a@example.com"))
    before = objects(storage)
    url = f"/projects/{lib['project'].id}"

    for wrong in ("my stream", "My Stream ", "", "Other"):
        response = client.request("DELETE", url, json={"confirm_name": wrong})
        assert response.status_code == 422 and "exact name" in response.json()["detail"]
    assert client.request("DELETE", url).status_code == 422  # no confirmation at all
    assert client.get(url).status_code == 200 and objects(storage) == before


def test_only_the_owner_can_delete_a_project(client, db_session, storage):
    lib = library(db_session, storage, sign_up(client, "owner@example.com"))
    url = f"/projects/{lib['project'].id}"
    sign_up(client, "intruder@example.com")
    assert client.request("DELETE", url, json={"confirm_name": "My Stream"}).status_code == 404
    client.cookies.clear()
    assert client.request("DELETE", url, json={"confirm_name": "My Stream"}).status_code == 401
    assert db_session.get(Project, lib["project"].id) is not None


def test_deleting_a_project_removes_its_rows_and_every_file(client, db_session, storage):
    other = library(db_session, storage, sign_up(client, "other@example.com"))
    others = objects(storage)
    lib = library(db_session, storage, sign_up(client, "a@example.com"))
    edit = ready_edit(client, db_session, storage, lib, {"layout": "center_crop"})
    mine = objects(storage) - others
    assert len(mine) == 4  # video, music, clip, edit
    ids = [(Project, lib["project"].id), (Video, lib["video"].id), (Clip, lib["clip"].id),
           (ClipEdit, edit.id), (AudioAsset, lib["music"].id)]  # fmt: skip
    project_id = lib["project"].id

    response = client.request(
        "DELETE", f"/projects/{project_id}", json={"confirm_name": "My Stream"}
    )

    assert response.status_code == 200
    assert response.json() == {"media_files_removed": 4, "media_files_pending_cleanup": 0}
    assert objects(storage) == others  # someone else's project is untouched
    db_session.expire_all()
    for model, row_id in ids:
        assert db_session.get(model, row_id) is None
    assert db_session.get(Project, other["project"].id) is not None
    assert client.get(f"/projects/{project_id}").status_code == 404


def test_a_storage_failure_is_counted_and_cleanup_finishes_the_job(
    client, db_session, storage, monkeypatch
):
    lib = library(db_session, storage, sign_up(client, "a@example.com"))
    video_key = lib["video"].storage_key
    real_delete = storage.delete

    def flaky(key):
        if key == video_key:
            raise StorageUnavailable("Object storage request failed")
        real_delete(key)

    monkeypatch.setattr(storage, "delete", flaky)
    response = client.request(
        "DELETE", f"/projects/{lib['project'].id}", json={"confirm_name": "My Stream"}
    )
    assert response.json() == {"media_files_removed": 2, "media_files_pending_cleanup": 1}
    assert video_key not in response.text
    assert objects(storage) == {video_key}  # the rows are gone; the file is now an orphan

    monkeypatch.setattr(storage, "delete", real_delete)
    report = cleanup(db_session, storage, storage.root.parent / "work", grace=timedelta(hours=1),
                     apply=True, now=datetime.now(UTC) + OLD)  # fmt: skip
    assert [key for key, _ in report.orphans] == [video_key] and report.removed == 1
    assert objects(storage) == set()


# --- audio assets and edits -----


def test_audio_in_use_cannot_be_deleted_until_its_edits_are(client, db_session, storage):
    lib = library(db_session, storage, sign_up(client, "a@example.com"))
    asset_url = f"/projects/{lib['project'].id}/audio-assets/{lib['music'].id}"
    music = {"music": {"asset_id": str(lib["music"].id)}}
    edit = ready_edit(client, db_session, storage, lib, {"layout": "center_crop", "audio": music})

    refused = client.delete(asset_url)
    assert refused.status_code == 409 and "used by 1 edit" in refused.json()["detail"]
    assert storage.exists(lib["music"].storage_key)

    assert client.delete(f"{lib['edits']}/{edit.id}").status_code == 200
    deleted = client.delete(asset_url)
    assert deleted.status_code == 200 and deleted.json()["media_files_removed"] == 1
    assert not storage.exists(lib["music"].storage_key)
    assert client.get(asset_url).status_code == 404


def test_deleting_an_edit_removes_only_its_short(client, db_session, storage):
    lib = library(db_session, storage, sign_up(client, "a@example.com"))
    edit = ready_edit(client, db_session, storage, lib, {"layout": "center_crop"})
    url = f"{lib['edits']}/{edit.id}"

    sign_up(client, "intruder@example.com")
    assert client.delete(url).status_code == 404
    client.cookies.clear()
    client.post("/auth/login", json={"email": "a@example.com", "password": PASSWORD})

    assert client.delete(url).status_code == 200
    assert not storage.exists(edit_storage_key(edit.id))
    assert storage.exists(lib["clip"].storage_key)  # the source clip is never touched
    assert client.get(url).status_code == 404
    assert client.get(f"/edits/{edit.id}/content").status_code == 404


def test_a_render_whose_clip_was_deleted_stores_nothing(db_session, storage):
    db_session.add(User(email="r@example.com", password_hash="x"))
    db_session.commit()
    lib = library(db_session, storage, "r@example.com")
    clip = lib["clip"]
    storage.delete(clip.storage_key)
    clip.status, clip.storage_key, clip.celery_task_id = "queued", None, "task-1"
    db_session.commit()
    clip_id = clip.id

    def deleting_renderer(source, target, *, start, end, options, heartbeat=None):
        target.write_bytes(b"rendered")
        db_session.execute(Clip.__table__.delete().where(Clip.id == clip_id))
        db_session.commit()
        heartbeat()
        return None

    render_pipeline.run_clip_render(
        clip_id, db_session, storage=storage, renderer=deleting_renderer, task_id="task-1"
    )

    store = ClipArtifactStore(storage)
    assert not storage.exists(clip_storage_key(clip_id))
    assert not store.scratch.path_for(f"clips/{clip_id}/clip-tmp-1.mp4").exists()


# --- cleanup -----


def age(path: Path, hours: float) -> None:
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


def test_cleanup_reports_then_removes_only_old_unreferenced_media(
    client, db_session, storage, tmp_path
):
    lib = library(db_session, storage, sign_up(client, "a@example.com"))
    old_orphan = put(storage, storage.generate_key("mp4"))
    young_orphan = put(storage, storage.generate_key("mp4"))
    legacy = put(storage, f"transcription/{uuid.uuid4()}/normalized.mp3")
    for key in (old_orphan, legacy, lib["video"].storage_key, lib["clip"].storage_key):
        age(storage.path_for(key), 72)
    partial = storage.path_for(old_orphan).with_name(".x.mp4.part")
    partial.write_bytes(b"half")
    age(partial, 72)
    work = tmp_path / "work"
    stale = work / "render" / str(uuid.uuid4()) / "task1"
    stale.mkdir(parents=True)
    (stale / "clip.mp4").write_bytes(b"x")
    for path in (stale / "clip.mp4", stale, stale.parent, stale.parent.parent):
        age(path, 72)
    fresh = work / "render" / str(uuid.uuid4()) / "task2"
    fresh.mkdir(parents=True)
    (fresh / "clip.mp4").write_bytes(b"in use")

    report = cleanup(db_session, storage, work, grace=timedelta(hours=24))

    assert sorted(key for key, _ in report.orphans) == sorted([old_orphan, legacy])
    assert report.partials == [partial.relative_to(storage.root).as_posix()]
    assert any(str(stale.parent.name) in entry for entry in report.scratch)
    assert all(str(fresh.parent.name) not in entry for entry in report.scratch)
    assert storage.exists(old_orphan) and partial.exists() and stale.exists()  # report only

    applied = cleanup(db_session, storage, work, grace=timedelta(hours=24), apply=True)

    assert applied.failed == 0
    assert not storage.exists(old_orphan) and not storage.exists(legacy) and not partial.exists()
    assert not stale.exists() and (fresh / "clip.mp4").exists()
    assert storage.exists(young_orphan)  # too young: could be an upload in progress
    for key in (lib["video"].storage_key, lib["music"].storage_key, lib["clip"].storage_key):
        assert storage.exists(key)  # referenced: never touched, however old


def test_cleanup_never_runs_with_a_grace_shorter_than_a_job(monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["cleanup", "--grace-hours", "1"])
    assert "job time limit" in str(excinfo.value)
