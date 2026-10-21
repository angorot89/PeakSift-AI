# ruff: noqa: F811 - pytest fixtures imported from test_semantic_lifecycle are parameters here
"""Semantic indexing and search stay cheap and bounded: concurrent requests make one index, a
search never touches media storage (vectors only), one model per process, model calls in
bounded batches, and no temporary frames or files are left behind."""

import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.api.deps import get_storage
from app.core.config import get_settings
from app.main import app
from app.models import VisualAsset, VisualSemanticIndex
from app.services.semantic import indexing, registry
from app.services.semantic.fake import FakeEmbeddingProvider
from app.services.semantic.indexing import request_index, run_semantic_index
from app.services.semantic.search import QUERY_CACHE
from tests.media_fixtures import requires_ffmpeg
from tests.test_semantic_lifecycle import jobs, upload  # noqa: F401 - fixture
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import make_image, make_video

pytestmark = requires_ffmpeg


@pytest.fixture(autouse=True)
def manual_indexing(monkeypatch):
    QUERY_CACHE.clear()
    monkeypatch.setattr("app.api.visual_assets.start_indexing_quietly", lambda *a: None)


@pytest.fixture
def project(client):
    sign_up(client, f"perf-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


def asset(db, asset_id) -> VisualAsset:
    return db.get(VisualAsset, uuid.UUID(asset_id))


def test_two_requests_at_the_same_moment_make_one_index(client, db_session, project, tmp_path,
                                                        monkeypatch):  # fmt: skip
    row = asset(db_session, upload(client, project, make_image(tmp_path / "a.jpg")).json()["id"])
    first = request_index(db_session, row, get_settings())
    assert first is not None
    # The second request looked before the first committed: it sees no index, tries to create
    # one, loses on the unique constraint and steps back.
    monkeypatch.setattr(indexing, "find_index", lambda *a: None)
    assert request_index(db_session, row, get_settings()) is None
    count = db_session.scalar(
        select(func.count()).select_from(VisualSemanticIndex)
        .where(VisualSemanticIndex.visual_asset_id == row.id)
    )  # fmt: skip
    assert count == 1


class NoStorage:
    """Any media access fails the test: search must read vectors only."""

    def __getattr__(self, name):
        raise AssertionError(f"search touched media storage ({name})")


def test_a_search_never_touches_media_storage(client, db_session, project, jobs, tmp_path):
    from app.services.semantic.lifecycle import start_indexing

    body = upload(client, project, make_image(tmp_path / "IMG_1.jpg", color=(45, 95, 190))).json()
    start_indexing(db_session, asset(db_session, body["id"]), get_settings())
    jobs.run()
    app.dependency_overrides[get_storage] = lambda: NoStorage()
    try:
        response = client.get(f"/projects/{project}/visual-assets/search", params={"q": "bridge"})
    finally:
        app.dependency_overrides.pop(get_storage, None)
    assert response.status_code == 200
    assert response.json()["results"][0]["asset"]["id"] == body["id"]


def test_one_model_per_process_across_jobs(client, db_session, project, tmp_path):
    registry.reset_providers()
    settings = get_settings()
    rows = [
        asset(db_session, upload(client, project, make_image(tmp_path / f"{n}.jpg",
                                                             color=(n * 60, 90, 120))).json()["id"])
        for n in range(3)
    ]  # fmt: skip
    for row in rows:
        index = request_index(db_session, row, settings)
        run_semantic_index(index.id, db_session, settings=settings, task_id=index.celery_task_id)
        assert index.status == "ready"
    (provider,) = registry._providers.values()  # built once, reused by every job
    assert isinstance(provider, FakeEmbeddingProvider) and provider.image_calls == 3
    registry.reset_providers()


def test_model_calls_stay_within_the_batch_size(client, db_session, project, tmp_path):
    batches: list[int] = []

    class Small(FakeEmbeddingProvider):
        batch_size = 2

        def embed_images(self, images):
            batches.append(len(images))
            return super().embed_images(images)

    video = make_video(tmp_path / "long.mp4", seconds=12.0)
    row = asset(db_session, upload(client, project, video).json()["id"])
    index = request_index(db_session, row, get_settings())
    run_semantic_index(index.id, db_session, settings=get_settings(), provider=Small(),
                       task_id=index.celery_task_id)  # fmt: skip
    assert index.status == "ready" and index.embedding_count == 6
    assert batches == [2, 2, 2]


def _scratch() -> list[Path]:
    root = Path(get_settings().work_root) / "semantic"
    return [p for p in root.rglob("*")] if root.exists() else []


def test_no_temporary_frames_or_files_are_left_behind(client, db_session, project, tmp_path):
    class Broken(FakeEmbeddingProvider):
        def embed_images(self, images):
            raise RuntimeError("boom")

    cases = [
        (make_image(tmp_path / "a.jpg"), FakeEmbeddingProvider(), "ready"),
        (make_video(tmp_path / "v.mp4", seconds=6.0), FakeEmbeddingProvider(), "ready"),
        (make_video(tmp_path / "w.mp4", seconds=4.0, size="160x90"), Broken(), "failed"),
    ]
    for path, provider, status in cases:
        row = asset(db_session, upload(client, project, path).json()["id"])
        index = request_index(db_session, row, get_settings())
        run_semantic_index(index.id, db_session, settings=get_settings(), provider=provider,
                           task_id=index.celery_task_id)  # fmt: skip
        assert index.status == status
        assert [p for p in _scratch() if p.is_file()] == []  # frames, fetched files: all gone


def test_images_reach_the_model_at_most_1024_pixels(client, db_session, project, tmp_path):
    seen: list[tuple[int, int]] = []

    class Recording(FakeEmbeddingProvider):
        def embed_images(self, images: list[Image.Image]):
            seen.extend(image.size for image in images)
            return super().embed_images(images)

    big = make_image(tmp_path / "big.png", (3000, 2000))
    row = asset(db_session, upload(client, project, big).json()["id"])
    index = request_index(db_session, row, get_settings())
    run_semantic_index(index.id, db_session, settings=get_settings(), provider=Recording(),
                       task_id=index.celery_task_id)  # fmt: skip
    assert seen and max(seen[0]) <= 1024
