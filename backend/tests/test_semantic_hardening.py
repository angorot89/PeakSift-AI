# ruff: noqa: F811 - pytest fixtures imported from test_semantic_lifecycle are parameters here
"""Semantic hardening: killed workers, deletions mid-job (asset, project, at the final commit),
media edge cases end to end (EXIF rotation, panoramas, portraits, a missing thumbnail), and
privacy — no vectors, pixels or local paths in logs, responses or stored messages."""

import io
import logging
import re
import uuid
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import select, text

from app.core.config import get_settings
from app.models import AssetEmbedding, VisualAsset, VisualSemanticIndex
from app.services.semantic import indexing
from app.services.semantic.fake import FakeEmbeddingProvider
from app.services.semantic.indexing import request_index, run_semantic_index
from app.services.semantic.search import QUERY_CACHE
from app.services.storage import media_storage
from tests.media_fixtures import requires_ffmpeg
from tests.test_semantic_lifecycle import jobs, upload  # noqa: F401 - fixture
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import make_image, make_video

pytestmark = requires_ffmpeg

FLOATS = re.compile(r"(-?\d\.\d{3,}[,\s]+){20,}")  # a vector-like run of numbers


@pytest.fixture(autouse=True)
def manual_indexing(monkeypatch):
    QUERY_CACHE.clear()
    monkeypatch.setattr("app.api.visual_assets.start_indexing_quietly", lambda *a: None)


@pytest.fixture
def project(client):
    sign_up(client, f"hard-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


def asset(db, asset_id) -> VisualAsset:
    return db.get(VisualAsset, uuid.UUID(asset_id))


class Recording(FakeEmbeddingProvider):
    def __init__(self):
        super().__init__()
        self.sizes: list[tuple[int, int]] = []

    def embed_images(self, images):
        self.sizes.extend(image.size for image in images)
        return super().embed_images(images)


def index_with(db, row, provider):
    index = request_index(db, row, get_settings())
    return run_semantic_index(index.id, db, settings=get_settings(), provider=provider,
                              task_id=index.celery_task_id)  # fmt: skip


# --- killed workers and deletions mid-job --------------------------------------------------------


def test_a_killed_worker_is_taken_over_and_never_writes_again(client, db_session, project,
                                                             tmp_path):  # fmt: skip
    row = asset(db_session, upload(client, project, make_image(tmp_path / "a.jpg")).json()["id"])
    index = request_index(db_session, row, get_settings())
    dead_task = index.celery_task_id
    index.status = "indexing"  # the worker started, then died without a trace
    index.heartbeat_at = indexing.now() - timedelta(hours=1)
    db_session.flush()
    retry = request_index(db_session, row, get_settings())
    assert retry is not None and retry.attempt == 2 and retry.celery_task_id != dead_task
    # The dead worker's task, delivered again, is ignored: the token moved on.
    assert run_semantic_index(index.id, db_session, settings=get_settings(),
                              provider=FakeEmbeddingProvider(), task_id=dead_task
                              ).status == "queued"  # fmt: skip
    done = run_semantic_index(
        index.id, db_session, settings=get_settings(), provider=FakeEmbeddingProvider(),
        task_id=retry.celery_task_id,
    )  # fmt: skip
    assert done.status == "ready" and done.embedding_count == 1


def test_a_project_deleted_during_indexing_stops_the_job(client, db_session, project, tmp_path):
    row = asset(db_session, upload(client, project, make_image(tmp_path / "a.jpg")).json()["id"])
    index = request_index(db_session, row, get_settings())
    index_id = index.id

    class DeleteProject(FakeEmbeddingProvider):
        def embed_images(self, images):
            response = client.request(
                "DELETE", f"/projects/{project}", json={"confirm_name": "Stream"}
            )
            assert response.status_code == 200
            return super().embed_images(images)

    run_semantic_index(index_id, db_session, settings=get_settings(), provider=DeleteProject(),
                       task_id=index.celery_task_id)  # fmt: skip
    db_session.expire_all()
    assert db_session.get(VisualSemanticIndex, index_id) is None
    assert not db_session.scalars(
        select(AssetEmbedding).where(AssetEmbedding.index_id == index_id)
    ).all()


def test_a_deletion_at_the_final_commit_stops_quietly(client, db_session, project, tmp_path,
                                                     monkeypatch, caplog):  # fmt: skip
    asset_id = upload(client, project, make_image(tmp_path / "a.jpg")).json()["id"]
    row = asset(db_session, asset_id)
    index = request_index(db_session, row, get_settings())
    index_id, task = index.id, index.celery_task_id

    class DeleteAtTheEnd(FakeEmbeddingProvider):
        def embed_images(self, images):
            vectors = super().embed_images(images)
            # Another process deletes the asset; this attempt's ownership check right before the
            # commit still passed (the race window). Raw SQL: nothing in this session knows.
            monkeypatch.setattr(indexing, "ensure_still_owner", lambda *a: None)
            db_session.execute(text("DELETE FROM visual_assets WHERE id = :id"), {"id": row.id})
            db_session.commit()  # the other process commits its deletion
            return vectors

    with caplog.at_level(logging.INFO):
        run_semantic_index(index_id, db_session, settings=get_settings(), provider=DeleteAtTheEnd(),
                           task_id=task)  # fmt: skip
    assert "Unexpected error" not in caplog.text
    assert "taken over or removed" in caplog.text
    db_session.expire_all()
    assert db_session.get(VisualSemanticIndex, index_id) is None


# --- media edge cases end to end ---------------------------------------------------------------


def jpeg_rotated(path, size=(400, 200)):
    image = Image.new("RGB", size, (200, 40, 40))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90°: the creator sees a portrait picture
    image.save(path, "JPEG", exif=exif)
    return path


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda p: jpeg_rotated(p / "phone.jpg"), "portrait"),
        (lambda p: make_image(p / "pano.jpg", (4000, 400)), "wide"),
        (lambda p: make_image(p / "tall.png", (300, 1200)), "portrait"),
        (lambda p: make_image(p / "tiny.png", (16, 16)), "square"),
    ],
    ids=["exif-rotated", "panorama", "portrait", "tiny"],
)
def test_unusual_images_are_indexed_as_the_creator_sees_them(client, db_session, project,
                                                            tmp_path, make, expected):  # fmt: skip
    row = asset(db_session, upload(client, project, make(tmp_path)).json()["id"])
    recording = Recording()
    index = index_with(db_session, row, recording)
    assert index.status == "ready", index.error_message
    (width, height) = recording.sizes[0]
    assert max(width, height) <= 1024
    if expected == "portrait":
        assert height > width
    elif expected == "wide":
        assert width >= 8 * height
    else:
        assert width == height


def test_a_missing_thumbnail_does_not_matter(client, db_session, project, tmp_path):
    row = asset(db_session, upload(client, project, make_image(tmp_path / "a.jpg")).json()["id"])
    media_storage(get_settings()).delete(row.thumbnail_storage_key)
    assert index_with(db_session, row, FakeEmbeddingProvider()).status == "ready"


def test_a_rotated_video_is_indexed_upright(client, db_session, project, tmp_path):
    from tests.visual_fixtures import rotate_metadata

    video = rotate_metadata(make_video(tmp_path / "v.mp4", size="320x180", seconds=3.0),
                            tmp_path / "phone.mp4", 90)  # fmt: skip
    row = asset(db_session, upload(client, project, video).json()["id"])
    recording = Recording()
    assert index_with(db_session, row, recording).status == "ready"
    assert all(height > width for width, height in recording.sizes)


# --- privacy -----------------------------------------------------------------------------------


def secrets_of_this_server() -> list[str]:
    settings = get_settings()
    return [str(settings.media_root), str(settings.work_root), settings.semantic_model_dir]


def test_logs_carry_no_vectors_pixels_or_paths(client, db_session, project, tmp_path, caplog,
                                              jobs):  # fmt: skip
    from app.services.semantic.lifecycle import start_indexing

    caplog.set_level(logging.DEBUG)
    good = asset(db_session, upload(client, project, make_image(tmp_path / "a.jpg")).json()["id"])
    bad = asset(db_session, upload(client, project, make_image(tmp_path / "b.jpg")).json()["id"])
    media_storage(get_settings()).delete(bad.storage_key)
    for row in (good, bad):
        start_indexing(db_session, row, get_settings())
    jobs.run()
    client.get(f"/projects/{project}/visual-assets/search", params={"q": "bridge structure"})
    text = caplog.text
    assert not FLOATS.search(text)  # no vectors
    assert "\\x" not in text and "PIL.Image" not in text  # no pixel data
    for secret in secrets_of_this_server():
        assert secret not in text


def test_responses_and_stored_messages_reveal_no_locations(client, db_session, project, jobs,
                                                          tmp_path):  # fmt: skip
    from app.services.semantic.lifecycle import start_indexing

    paths = [make_image(tmp_path / f"{n}.jpg", color=(n * 70, 80, 90)) for n in range(2)]
    rows = [asset(db_session, upload(client, project, path).json()["id"]) for path in paths]
    media_storage(get_settings()).delete(rows[1].storage_key)
    for row in rows:
        start_indexing(db_session, row, get_settings())
    jobs.run()
    messages = [m for m in db_session.scalars(select(VisualSemanticIndex.error_message)) if m]
    bodies = [
        client.get(f"/projects/{project}/visual-assets").text,
        client.get(f"/projects/{project}/visual-assets/search", params={"q": "bridge"}).text,
        client.post(f"/projects/{project}/visual-assets/{rows[1].id}/visual-search/retry").text,
    ]
    for body in [*bodies, *messages]:
        for secret in secrets_of_this_server():
            assert secret not in body
        assert not FLOATS.search(body)
    assert messages and all("/" not in m for m in messages)


def test_an_uploaded_image_is_never_reinterpreted(client, db_session, project, tmp_path):
    """The indexer reads the stored rendition as JPEG/PNG only; a file swapped behind its back
    for another format is refused, not decoded as whatever it claims to be."""
    row = asset(db_session, upload(client, project, make_image(tmp_path / "a.jpg")).json()["id"])
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buffer, "GIF")
    media_storage(get_settings()).path_for(row.storage_key).write_bytes(buffer.getvalue())
    index = index_with(db_session, row, FakeEmbeddingProvider())
    assert index.status == "failed" and index.error_code == "unreadable_image"
