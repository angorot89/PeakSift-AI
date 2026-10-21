"""Image semantic indexing: requesting (one index per model, retries, attempts, turned off),
the job (storage → workspace → canonical pixels → validated vectors, one commit), reuse of an
identical file's vectors within one owner only, attempt ownership, and failures that never
make the asset unusable or leak internals."""

import uuid
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AssetEmbedding, VisualAsset, VisualSemanticIndex
from app.services.semantic import indexing
from app.services.semantic.contract import EmbeddingFailure, EmbeddingUnavailable
from app.services.semantic.fake import FAKE_IDENTITY, FakeEmbeddingProvider
from app.services.semantic.indexing import (
    TooManyAttempts,
    request_index,
    run_semantic_index,
)
from app.services.semantic.vectors import cosine
from app.services.storage import StorageUnavailable, media_storage
from tests.media_fixtures import requires_ffmpeg
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import make_image, make_transparent_png

pytestmark = requires_ffmpeg

BLUE = (45, 95, 190)  # the fake provider's "bridge"
RED = (215, 70, 45)  # its "rocket"


@pytest.fixture(autouse=True)
def manual_indexing(monkeypatch):
    """These tests drive ``request_index`` themselves: uploads here do not start indexing."""
    monkeypatch.setattr("app.api.visual_assets.start_indexing_quietly", lambda *a: None)


@pytest.fixture
def settings():
    return get_settings().model_copy(update={"semantic_provider": "fake"})


@pytest.fixture
def fake():
    return FakeEmbeddingProvider()


@pytest.fixture
def project(client):
    sign_up(client, f"indexer-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


def upload(client, project_id, path: Path) -> VisualAsset:
    with path.open("rb") as handle:
        response = client.post(
            f"/projects/{project_id}/visual-assets", files={"file": (path.name, handle.read())}
        )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def asset_row(db, asset_id) -> VisualAsset:
    return db.get(VisualAsset, uuid.UUID(asset_id))


def index_now(db, asset, settings, fake, **kwargs) -> VisualSemanticIndex:
    index = request_index(db, asset, settings)
    assert index is not None and index.status == "queued" and index.celery_task_id
    return run_semantic_index(
        index.id, db, settings=settings, provider=fake, task_id=index.celery_task_id, **kwargs
    )


def vectors(db, index) -> list[np.ndarray]:
    rows = db.scalars(
        select(AssetEmbedding)
        .where(AssetEmbedding.index_id == index.id)
        .order_by(AssetEmbedding.frame_index)
    )
    return [np.asarray(row.embedding) for row in rows]


def test_an_untagged_image_is_indexed_by_what_it_shows(client, db_session, project, settings,
                                                       fake, tmp_path):  # fmt: skip
    asset_id = upload(client, project, make_image(tmp_path / "IMG_7834.jpg", color=BLUE))
    asset = asset_row(db_session, asset_id)
    index = index_now(db_session, asset, settings, fake)
    assert index.status == "ready" and index.embedding_count == 1 and not index.reused
    assert (index.frames_total, index.frames_done) == (1, 1)
    assert index.identity == FAKE_IDENTITY.key and index.source_sha256 == asset.sha256
    assert index.config["batch_size"] == settings.semantic_batch_size
    (vector,) = vectors(db_session, index)
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)
    assert cosine(vector, fake.embed_text("bridge structure")) > 0.8  # content, not the name
    assert cosine(vector, fake.embed_text("rocket launch")) < 0.3
    # The asset itself is untouched.
    assert asset.display_name == "IMG_7834.jpg" and asset.tags == [] and asset.description == ""


def test_a_transparent_image_is_embedded_on_neutral_grey(client, db_session, project, settings,
                                                       tmp_path):  # fmt: skip
    seen: list[Image.Image] = []

    class Recording(FakeEmbeddingProvider):
        def embed_images(self, images):
            seen.extend(images)
            return super().embed_images(images)

    asset_id = upload(client, project, make_transparent_png(tmp_path / "logo.png"))
    index = index_now(db_session, asset_row(db_session, asset_id), settings, Recording())
    assert index.status == "ready"
    assert seen[0].mode == "RGB" and seen[0].getpixel((1, 1)) == (128, 128, 128)


def test_request_index_is_idempotent_per_model(client, db_session, project, settings, fake,
                                               tmp_path):  # fmt: skip
    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    first = request_index(db_session, asset, settings)
    assert request_index(db_session, asset, settings) is None  # queued and live: not twice
    run_semantic_index(first.id, db_session, settings=settings, provider=fake,
                       task_id=first.celery_task_id)  # fmt: skip
    assert request_index(db_session, asset, settings) is None  # ready: reused
    assert request_index(db_session, asset, settings, retry=True) is None
    # Turned off: nothing to start, and nothing is created.
    off = settings.model_copy(update={"semantic_provider": "disabled"})
    assert request_index(db_session, asset, off) is None
    assert len(asset.semantic_indexes) == 1


def test_a_stalled_queued_index_can_be_requested_again(client, db_session, project, settings,
                                                      tmp_path):  # fmt: skip
    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    index = request_index(db_session, asset, settings)
    old_task = index.celery_task_id
    index.created_at = index.updated_at = indexing.now() - timedelta(hours=1)
    db_session.flush()
    again = request_index(db_session, asset, settings)
    assert again is not None and again.id == index.id and again.attempt == 2
    assert again.celery_task_id != old_task


def test_failure_keeps_the_asset_usable_and_retry_is_bounded(client, db_session, project,
                                                             settings, tmp_path):  # fmt: skip
    class Broken(FakeEmbeddingProvider):
        def embed_images(self, images):
            raise EmbeddingFailure("The visual search model failed on an image")

    asset_id = upload(client, project, make_image(tmp_path / "a.jpg"))
    asset = asset_row(db_session, asset_id)
    index = index_now(db_session, asset, settings, Broken())
    assert index.status == "failed" and index.error_code == "embedding_failed"
    assert index.embedding_count is None and vectors(db_session, index) == []
    assert client.get(f"/projects/{project}/visual-assets/{asset_id}").status_code == 200
    assert request_index(db_session, asset, settings) is None  # failed waits for a retry
    retried = request_index(db_session, asset, settings, retry=True)
    assert retried.attempt == 2 and retried.status == "queued" and retried.error_code is None
    for _ in range(settings.semantic_max_attempts - 2):
        run_semantic_index(retried.id, db_session, settings=settings, provider=Broken(),
                           task_id=retried.celery_task_id)  # fmt: skip
        retried = request_index(db_session, asset, settings, retry=True)
    run_semantic_index(retried.id, db_session, settings=settings, provider=Broken(),
                       task_id=retried.celery_task_id)  # fmt: skip
    with pytest.raises(TooManyAttempts):
        request_index(db_session, asset, settings, retry=True)


def test_model_unavailable_is_recorded_without_internals(client, db_session, project, settings,
                                                         tmp_path):  # fmt: skip
    class Missing(FakeEmbeddingProvider):
        def embed_images(self, images):
            raise EmbeddingUnavailable("The visual search model is not installed on this server")

    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    index = index_now(db_session, asset, settings, Missing())
    assert index.status == "failed" and index.error_code == "model_unavailable"
    assert "/" not in index.error_message


@pytest.mark.parametrize("output", ["nan", "zero", "short", "count"])
def test_invalid_vectors_are_never_stored(client, db_session, project, settings, tmp_path,
                                          output):  # fmt: skip
    class Bad(FakeEmbeddingProvider):
        def embed_images(self, images):
            if output == "count":
                return []
            value = {"nan": np.full(512, np.nan), "zero": np.zeros(512), "short": np.ones(3)}
            return [value[output] for _ in images]

    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    index = index_now(db_session, asset, settings, Bad())
    assert index.status == "failed" and index.error_code == "embedding_failed"
    assert vectors(db_session, index) == []


def test_missing_and_unavailable_storage(client, db_session, project, settings, fake, tmp_path,
                                         monkeypatch):  # fmt: skip
    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    media_storage(settings).delete(asset.storage_key)
    index = index_now(db_session, asset, settings, fake)
    assert index.status == "failed" and index.error_code == "asset_missing"

    other = asset_row(db_session, upload(client, project, make_image(tmp_path / "b.jpg",
                                                                     color=RED)))  # fmt: skip

    class Down:
        def fetch(self, key, directory):
            raise StorageUnavailable("down")

    index = request_index(db_session, other, settings)
    run_semantic_index(index.id, db_session, settings=settings, storage=Down(), provider=fake,
                       task_id=index.celery_task_id)  # fmt: skip
    assert index.status == "failed" and index.error_code == "storage_unavailable"


def test_a_corrupt_stored_image_fails_cleanly(client, db_session, project, settings, fake,
                                              tmp_path):  # fmt: skip
    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    path = media_storage(settings).path_for(asset.storage_key)
    path.write_bytes(b"\xff\xd8\xff garbage")
    index = index_now(db_session, asset, settings, fake)
    assert index.status == "failed" and index.error_code == "unreadable_image"


def test_an_older_attempt_never_writes_after_a_takeover(client, db_session, project, settings,
                                                        fake, tmp_path):  # fmt: skip
    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    index = request_index(db_session, asset, settings)
    old_task = index.celery_task_id

    class TakenOver(FakeEmbeddingProvider):
        def embed_images(self, images):
            # A retry takes the index over while this attempt is still embedding.
            index.celery_task_id = "newer-attempt"
            db_session.commit()
            return super().embed_images(images)

    run_semantic_index(index.id, db_session, settings=settings, provider=TakenOver(),
                       task_id=old_task)  # fmt: skip
    db_session.refresh(index)
    assert index.status == "indexing" and index.celery_task_id == "newer-attempt"
    assert vectors(db_session, index) == []
    # A stray duplicate of the old task is ignored outright.
    assert run_semantic_index(index.id, db_session, settings=settings, provider=fake,
                              task_id=old_task).status == "indexing"  # fmt: skip


def test_a_deleted_asset_stops_the_job(client, db_session, project, settings, tmp_path):
    asset_id = upload(client, project, make_image(tmp_path / "a.jpg"))
    asset = asset_row(db_session, asset_id)
    index = request_index(db_session, asset, settings)
    index_id = index.id

    class DeletedMeanwhile(FakeEmbeddingProvider):
        def embed_images(self, images):
            response = client.delete(f"/projects/{project}/visual-assets/{asset_id}")
            assert response.status_code == 200
            return super().embed_images(images)

    run_semantic_index(index_id, db_session, settings=settings, provider=DeletedMeanwhile(),
                       task_id=index.celery_task_id)  # fmt: skip
    db_session.expire_all()
    assert db_session.get(VisualSemanticIndex, index_id) is None
    assert (
        db_session.scalars(select(AssetEmbedding).where(AssetEmbedding.index_id == index_id)).all()
        == []
    )
    assert run_semantic_index(index_id, db_session, settings=settings) is None


def test_identical_file_of_the_same_owner_reuses_vectors(client, db_session, settings, fake,
                                                        tmp_path):  # fmt: skip
    sign_up(client, f"owner-{uuid.uuid4().hex[:8]}@example.com")
    first, second = create_project(client)["id"], create_project(client)["id"]
    image = make_image(tmp_path / "bridge.jpg", color=BLUE)
    a = asset_row(db_session, upload(client, first, image))
    b = asset_row(db_session, upload(client, second, image))
    original = index_now(db_session, a, settings, fake)
    calls = fake.image_calls
    copy = index_now(db_session, b, settings, fake)
    assert copy.status == "ready" and copy.reused and fake.image_calls == calls  # no model run
    copied, source = vectors(db_session, copy), vectors(db_session, original)
    assert len(copied) == len(source) == 1
    assert np.allclose(copied[0], source[0], atol=1e-6)  # re-validated, same direction


def test_vectors_never_cross_owners(client, db_session, settings, fake, tmp_path):
    image = make_image(tmp_path / "bridge.jpg", color=BLUE)
    sign_up(client, f"alice-{uuid.uuid4().hex[:8]}@example.com")
    a = asset_row(db_session, upload(client, create_project(client)["id"], image))
    index_now(db_session, a, settings, fake)
    client.post("/auth/logout")
    sign_up(client, f"bob-{uuid.uuid4().hex[:8]}@example.com")
    b = asset_row(db_session, upload(client, create_project(client)["id"], image))
    calls = fake.image_calls
    index = index_now(db_session, b, settings, fake)
    assert not index.reused and fake.image_calls == calls + 1


def test_a_new_model_makes_the_old_index_stale_and_replaces_it(client, db_session, project,
                                                               settings, fake, tmp_path,
                                                               monkeypatch):  # fmt: skip
    from app.services.semantic import registry
    from app.services.semantic.state import EmbeddingIdentity, SemanticState, semantic_state

    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    old = index_now(db_session, asset, settings, fake)
    newer = EmbeddingIdentity("fake", "palette-concepts", "2", "semantic_v1", 512)
    monkeypatch.setattr(registry, "configured_identity", lambda s: newer)
    monkeypatch.setattr(indexing, "configured_identity", lambda s: newer)
    assert semantic_state(asset.semantic_indexes, newer) == SemanticState.STALE

    class Newer(FakeEmbeddingProvider):
        identity = newer

    index = request_index(db_session, asset, settings)
    assert index.id != old.id and index.model_version == "2"
    run_semantic_index(index.id, db_session, settings=settings, provider=Newer(),
                       task_id=index.celery_task_id)  # fmt: skip
    db_session.expire_all()
    rows = db_session.scalars(
        select(VisualSemanticIndex).where(VisualSemanticIndex.visual_asset_id == asset.id)
    ).all()
    assert [r.model_version for r in rows] == ["2"]  # the stale index is gone once replaced


def test_a_provider_for_another_model_is_refused(client, db_session, project, settings, fake,
                                                 tmp_path):  # fmt: skip
    from app.services.semantic.state import EmbeddingIdentity

    class Other(FakeEmbeddingProvider):
        identity = EmbeddingIdentity("fake", "palette-concepts", "9", "semantic_v1", 512)

    asset = asset_row(db_session, upload(client, project, make_image(tmp_path / "a.jpg")))
    index = index_now(db_session, asset, settings, Other())
    assert index.status == "failed" and index.error_code == "model_changed"


def test_the_task_takes_ids_only(client, db_session, project, settings, fake, tmp_path,
                                 monkeypatch):  # fmt: skip
    from app.workers.semantic_tasks import index_visual_asset_task

    calls = []
    monkeypatch.setattr(
        "app.workers.semantic_tasks.run_semantic_index",
        lambda index_id, db, task_id: calls.append((index_id, task_id)),
    )
    index_visual_asset_task.apply(args=["not-a-uuid"])
    assert calls == []
    some = uuid.uuid4()
    index_visual_asset_task.apply(args=[str(some)], task_id="t-1")
    assert calls == [(some, "t-1")]
