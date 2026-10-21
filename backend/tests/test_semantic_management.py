# ruff: noqa: F811 - pytest fixtures imported from test_semantic_lifecycle are parameters here
"""Managing visual search per asset: retrying a failed analysis without re-uploading, bounded
attempts, a lazy and bounded re-queue of stale assets after a model change, ownership, and
deleting an asset (its indexes and vectors go with it; storage cleanup is unchanged)."""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import AssetEmbedding, VisualSemanticIndex
from app.services.semantic import lifecycle
from app.services.semantic.contract import EmbeddingFailure
from app.services.semantic.fake import FakeEmbeddingProvider
from app.services.semantic.registry import install_provider, reset_providers
from app.services.semantic.state import EmbeddingIdentity
from tests.media_fixtures import requires_ffmpeg
from tests.test_semantic_lifecycle import jobs, upload  # noqa: F401 - fixture
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import make_image

pytestmark = requires_ffmpeg


@pytest.fixture
def project(client):
    sign_up(client, f"manager-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


def retry(client, project_id, asset_id):
    return client.post(f"/projects/{project_id}/visual-assets/{asset_id}/visual-search/retry")


class Broken(FakeEmbeddingProvider):
    def embed_images(self, images):
        raise EmbeddingFailure("The visual search model failed on an image")


def install(provider):
    reset_providers()
    install_provider(get_settings(), provider)


def test_a_failed_analysis_is_retried_without_reuploading(client, project, jobs, tmp_path):
    install(Broken())
    body = upload(client, project, make_image(tmp_path / "IMG_1.jpg")).json()
    jobs.run()
    state = client.get(f"/projects/{project}/visual-assets/{body['id']}").json()["visual_search"]
    assert state["state"] == "failed" and state["can_retry"] is True
    install(jobs.fake)
    response = retry(client, project, body["id"])
    assert response.status_code == 200
    assert response.json()["visual_search"]["state"] == "queued" and len(jobs.queued) == 1
    jobs.run()
    state = client.get(f"/projects/{project}/visual-assets/{body['id']}").json()["visual_search"]
    assert state["state"] == "ready"
    # Same asset, same file: nothing was uploaded again.
    assert len(client.get(f"/projects/{project}/visual-assets").json()) == 1


def test_retry_leaves_a_ready_or_running_analysis_alone(client, project, jobs, tmp_path):
    body = upload(client, project, make_image(tmp_path / "IMG_1.jpg")).json()
    assert retry(client, project, body["id"]).json()["visual_search"]["state"] == "queued"
    assert len(jobs.queued) == 1  # already queued: not started twice
    jobs.run()
    assert retry(client, project, body["id"]).json()["visual_search"]["state"] == "ready"
    assert jobs.queued == []


def test_attempts_are_bounded(client, project, jobs, db_session, tmp_path):
    install(Broken())
    body = upload(client, project, make_image(tmp_path / "IMG_1.jpg")).json()
    jobs.run()
    index = db_session.scalar(
        select(VisualSemanticIndex).where(VisualSemanticIndex.visual_asset_id == body["id"])
    )
    index.attempt = get_settings().semantic_max_attempts
    db_session.flush()
    state = client.get(f"/projects/{project}/visual-assets/{body['id']}").json()["visual_search"]
    assert state["state"] == "failed" and state["can_retry"] is False
    response = retry(client, project, body["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == "Visual analysis failed too many times for this file"


def test_retry_is_owner_only_and_needs_visual_search(client, project, jobs, monkeypatch,
                                                     tmp_path):  # fmt: skip
    body = upload(client, project, make_image(tmp_path / "IMG_1.jpg")).json()
    off = get_settings().model_copy(update={"semantic_provider": "disabled"})
    monkeypatch.setattr("app.api.visual_assets.get_settings", lambda: off)
    response = retry(client, project, body["id"])
    assert response.status_code == 409 and "turned off" in response.json()["detail"]
    monkeypatch.undo()
    client.post("/auth/logout")
    assert retry(client, project, body["id"]).status_code == 401
    sign_up(client, f"intruder-{uuid.uuid4().hex[:8]}@example.com")
    assert retry(client, project, body["id"]).status_code == 404


def test_a_model_change_requeues_stale_assets_lazily_and_boundedly(
    client, project, jobs, monkeypatch, tmp_path
):
    for n in range(5):
        upload(client, project, make_image(tmp_path / f"IMG_{n}.jpg", color=(40 * n, 90, 120)))
    jobs.run()
    newer = EmbeddingIdentity("fake", "palette-concepts", "2", "semantic_v1", 512)

    class Newer(FakeEmbeddingProvider):
        identity = newer

    for module in ("app.services.semantic.lifecycle", "app.services.semantic.indexing",
                   "app.api.visual_assets"):  # fmt: skip
        monkeypatch.setattr(f"{module}.configured_identity", lambda s: newer)
    install(Newer())
    listed = client.get(f"/projects/{project}/visual-assets").json()
    states = sorted(a["visual_search"]["state"] for a in listed)
    assert states == ["queued", "queued", "queued", "stale", "stale"]  # bounded per listing
    assert len(jobs.queued) == 3
    client.get(f"/projects/{project}/visual-assets")  # the next listing continues
    assert len(jobs.queued) == 5
    jobs.run()
    listed = client.get(f"/projects/{project}/visual-assets").json()
    assert {a["visual_search"]["state"] for a in listed} == {"ready"}


def test_lazy_requeue_never_restarts_failed_assets_and_can_be_off(
    client, project, jobs, monkeypatch, tmp_path
):
    install(Broken())
    upload(client, project, make_image(tmp_path / "IMG_1.jpg"))
    jobs.run()
    client.get(f"/projects/{project}/visual-assets")
    assert jobs.queued == []  # failed waits for the creator's retry
    zero = get_settings().model_copy(update={"semantic_lazy_reindex_per_request": 0})
    assert lifecycle.start_lazy_indexing(None, [], zero) == 0


def test_deleting_an_asset_removes_its_indexes_and_vectors(client, project, jobs, db_session,
                                                          tmp_path):  # fmt: skip
    keep = upload(client, project, make_image(tmp_path / "IMG_1.jpg")).json()
    gone = upload(client, project, make_image(tmp_path / "IMG_2.jpg", color=(200, 90, 40))).json()
    jobs.run()

    def counts():
        return (
            db_session.scalar(select(func.count()).select_from(VisualSemanticIndex)),
            db_session.scalar(select(func.count()).select_from(AssetEmbedding)),
        )

    before = counts()
    response = client.delete(f"/projects/{project}/visual-assets/{gone['id']}")
    assert response.status_code == 200
    assert response.json()["media_files_removed"] == 2  # the file and its thumbnail, as before
    db_session.expire_all()
    after = counts()
    assert (before[0] - after[0], before[1] - after[1]) == (1, 1)
    state = client.get(f"/projects/{project}/visual-assets/{keep['id']}").json()["visual_search"]
    assert state["state"] == "ready"
