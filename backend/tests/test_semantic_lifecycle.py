"""Semantic indexing in the upload lifecycle: an upload starts indexing in the background and
never waits for (or fails because of) it; the API reports each asset's visual-search state with
real progress and safe messages; the job is routed by configuration; the operator command
reindexes stale, missing and failed assets in bounded batches."""

import uuid

import pytest
from sqlalchemy import select

from app.cli import semantic as cli
from app.core.config import get_settings
from app.models import VisualAsset, VisualSemanticIndex
from app.services.semantic import indexing
from app.services.semantic.fake import FakeEmbeddingProvider
from app.services.semantic.registry import install_provider, reset_providers
from app.services.semantic.state import EmbeddingIdentity
from app.workers import dispatch
from app.workers.dispatch import JobQueueUnavailable
from tests.media_fixtures import requires_ffmpeg
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import make_image, make_video

pytestmark = requires_ffmpeg

BLUE = (45, 95, 190)


@pytest.fixture
def jobs(monkeypatch, db_session):
    """Enqueueing records the job; ``run()`` then executes it in the test's session."""
    queued: list[tuple[uuid.UUID, str]] = []
    fake = FakeEmbeddingProvider()
    reset_providers()
    install_provider(get_settings(), fake)

    def enqueue(index_id, *, task_id):
        # The token is committed before the job is enqueued.
        row = db_session.get(VisualSemanticIndex, index_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append((index_id, task_id))
        return task_id

    def run():
        while queued:
            index_id, task_id = queued.pop(0)
            indexing.run_semantic_index(index_id, db_session, task_id=task_id)

    monkeypatch.setattr(dispatch, "enqueue_semantic_index", enqueue)
    jobs = type("Jobs", (), {"queued": queued, "run": staticmethod(run), "fake": fake})
    yield jobs
    reset_providers()


@pytest.fixture
def project(client):
    sign_up(client, f"life-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


def upload(client, project_id, path):
    with path.open("rb") as handle:
        return client.post(
            f"/projects/{project_id}/visual-assets", files={"file": (path.name, handle.read())}
        )


def test_an_upload_returns_at_once_and_indexing_follows(client, project, jobs, tmp_path):
    response = upload(client, project, make_image(tmp_path / "IMG_0001.jpg", color=BLUE))
    assert response.status_code == 201
    body = response.json()
    assert body["visual_search"] == {
        "state": "queued", "frames_done": None, "frames_total": None, "message": None,
        "can_retry": False,
    }  # fmt: skip
    assert len(jobs.queued) == 1 and jobs.fake.image_calls == 0  # nothing ran in the request
    jobs.run()
    listed = client.get(f"/projects/{project}/visual-assets").json()
    assert listed[0]["visual_search"]["state"] == "ready"
    one = client.get(f"/projects/{project}/visual-assets/{body['id']}").json()
    assert one["visual_search"]["state"] == "ready"
    # A duplicate upload returns the asset and starts nothing new.
    again = upload(client, project, make_image(tmp_path / "IMG_0001.jpg", color=BLUE))
    assert again.status_code == 200 and jobs.queued == []


def test_the_response_never_exposes_vectors_or_model_internals(client, project, jobs, tmp_path):
    upload(client, project, make_image(tmp_path / "a.jpg"))
    jobs.run()
    text = client.get(f"/projects/{project}/visual-assets").text
    for internal in ("embedding", "palette-concepts", "model_version", "celery", "sha256"):
        assert internal not in text


def test_a_broker_outage_never_fails_the_upload(client, project, monkeypatch, tmp_path):
    def down(index_id, *, task_id):
        raise JobQueueUnavailable("The job queue is unavailable")

    monkeypatch.setattr(dispatch, "enqueue_semantic_index", down)
    response = upload(client, project, make_image(tmp_path / "a.jpg"))
    assert response.status_code == 201
    state = response.json()["visual_search"]
    assert state["state"] == "failed" and state["can_retry"] is True
    assert state["message"] == "Visual analysis could not start; try again"


def test_an_unexpected_indexing_error_never_fails_the_upload(client, project, monkeypatch,
                                                            tmp_path):  # fmt: skip
    def broken(*args, **kwargs):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(indexing, "request_index", broken)
    monkeypatch.setattr("app.services.semantic.lifecycle.request_index", broken)
    response = upload(client, project, make_image(tmp_path / "a.jpg"))
    assert response.status_code == 201
    assert response.json()["visual_search"]["state"] == "not_indexed"


def test_turned_off_reports_unavailable_and_starts_nothing(client, project, jobs, monkeypatch,
                                                          tmp_path):  # fmt: skip
    off = get_settings().model_copy(update={"semantic_provider": "disabled"})
    monkeypatch.setattr("app.api.visual_assets.get_settings", lambda: off)
    response = upload(client, project, make_image(tmp_path / "a.jpg"))
    assert response.json()["visual_search"]["state"] == "unavailable" and jobs.queued == []


def test_a_failed_index_reports_a_safe_message(client, project, jobs, db_session, tmp_path):
    class Missing(FakeEmbeddingProvider):
        def embed_images(self, images):
            from app.services.semantic.contract import EmbeddingUnavailable

            raise EmbeddingUnavailable("The visual search model is not installed on this server")

    reset_providers()
    install_provider(get_settings(), Missing())
    body = upload(client, project, make_image(tmp_path / "a.jpg")).json()
    jobs.run()
    state = client.get(f"/projects/{project}/visual-assets/{body['id']}").json()["visual_search"]
    assert state["state"] == "failed" and state["can_retry"] is True
    assert state["message"] == "The visual search model is not installed on this server"


def test_video_progress_is_real(client, project, jobs, db_session, tmp_path):
    body = upload(client, project, make_video(tmp_path / "v.mp4", seconds=6.0)).json()
    index = db_session.scalar(
        select(VisualSemanticIndex).where(VisualSemanticIndex.visual_asset_id == body["id"])
    )
    index.status, index.frames_total, index.frames_done = "indexing", 3, 1
    db_session.flush()
    state = client.get(f"/projects/{project}/visual-assets/{body['id']}").json()["visual_search"]
    assert state == {"state": "indexing", "frames_done": 1, "frames_total": 3, "message": None,
                     "can_retry": False}  # fmt: skip


def test_the_job_is_routed_by_configuration(monkeypatch):
    from app.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    expected = get_settings().semantic_queue
    if expected:
        assert routes["peaksift.index_visual_asset"] == {"queue": expected}
    else:  # default: the default queue, which every worker consumes
        assert "peaksift.index_visual_asset" not in routes


# --- the operator command ------------------------------------------------------------------


@pytest.fixture
def operator_session(monkeypatch, db_session):
    class Same:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "SessionLocal", lambda: Same())


def test_status_and_reindex_stale_missing_and_failed(client, project, jobs, db_session,
                                                    operator_session, capsys, tmp_path,
                                                    monkeypatch):  # fmt: skip
    ids = [upload(client, project, make_image(tmp_path / f"{n}.jpg", color=(n * 40, 90, 120)))
           .json()["id"] for n in range(1, 5)]  # fmt: skip
    jobs.run()
    assets = [db_session.get(VisualAsset, uuid.UUID(i)) for i in ids]
    # One never indexed, one failed, one made by an older model, one current.
    db_session.delete(assets[0].semantic_indexes[0])
    failed = assets[1].semantic_indexes[0]
    failed.status, failed.error_code, failed.embedding_count = "failed", "embedding_failed", None
    assets[2].semantic_indexes[0].model_version = "0"
    db_session.flush()
    db_session.expire_all()

    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "not_indexed  1" in out and "failed  1" in out and "stale  1" in out
    assert "ready  1" in out

    assert cli.main(["reindex", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.count("would index") == 2 and jobs.queued == []  # stale + missing by default

    assert cli.main(["reindex", "--failed", "--limit", "1"]) == 0
    assert len(jobs.queued) == 1  # bounded
    assert cli.main(["reindex", "--stale", "--missing", "--failed"]) == 0
    jobs.run()
    db_session.expire_all()
    states = cli.semantic_state  # the same derivation the API uses
    identity = cli.configured_identity(get_settings())
    assert all(
        states(db_session.get(VisualAsset, uuid.UUID(i)).semantic_indexes, identity).value
        == "ready"
        for i in ids
    )
    assert "queued" in capsys.readouterr().out


def test_reindex_is_scoped_to_a_project_and_refuses_when_off(client, jobs, db_session,
                                                            operator_session, capsys,
                                                            monkeypatch, tmp_path):  # fmt: skip
    sign_up(client, f"ops-{uuid.uuid4().hex[:8]}@example.com")
    first, second = create_project(client)["id"], create_project(client)["id"]
    upload(client, first, make_image(tmp_path / "a.jpg"))
    upload(client, second, make_image(tmp_path / "b.jpg", color=BLUE))
    for row in db_session.scalars(select(VisualSemanticIndex)).all():
        db_session.delete(row)
    db_session.flush()
    jobs.queued.clear()
    assert cli.main(["reindex", "--project", first]) == 0
    assert len(jobs.queued) == 1
    off = get_settings().model_copy(update={"semantic_provider": "disabled"})
    monkeypatch.setattr(cli, "get_settings", lambda: off)
    assert cli.main(["reindex"]) == 1
    assert cli.main(["status"]) == 0 and "turned off" in capsys.readouterr().out


def test_the_operator_command_never_embeds_in_its_own_process(
    jobs, operator_session, client, project, tmp_path
):
    upload(client, project, make_image(tmp_path / "a.jpg"))
    jobs.queued.clear()
    calls = jobs.fake.image_calls
    cli.main(["reindex", "--missing", "--stale"])
    assert jobs.fake.image_calls == calls  # only enqueued; workers embed


def test_identity_change_marks_every_index_stale(client, project, jobs, db_session,
                                                monkeypatch, tmp_path):  # fmt: skip
    upload(client, project, make_image(tmp_path / "a.jpg"))
    jobs.run()
    newer = EmbeddingIdentity("fake", "palette-concepts", "2", "semantic_v1", 512)
    monkeypatch.setattr("app.services.semantic.lifecycle.configured_identity", lambda s: newer)
    listed = client.get(f"/projects/{project}/visual-assets").json()
    assert listed[0]["visual_search"]["state"] == "stale"
