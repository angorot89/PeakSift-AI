"""The publishing API: owner-scoped, idempotent, honest about state, and never exposing
tokens, session URIs, task ids or storage keys."""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import publish_jobs as api
from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.main import app
from app.models import ConnectionStatus, PublishJob, PublishStatus
from app.services.publishing import pipeline
from app.services.publishing.fake import FakePublishingProvider
from app.services.publishing.provider import PublishErrorCode
from app.services.storage import LocalStorageProvider
from app.workers.dispatch import JobQueueUnavailable
from tests.publishing_fixtures import KEY, connect, ready_edit

DATA = b"\x00" * 300_000
BODY = {"title": "My first short", "description": "Made with PeakSift", "tags": ["clips"]}
PUBLIC_FIELDS = {
    "id", "edit_id", "provider", "status", "progress_percent", "bytes_uploaded", "bytes_total",
    "title", "description", "tags", "privacy", "made_for_kids", "video_url", "studio_url",
    "simulated", "error_code", "error_message", "retryable", "is_stale",
    "awaiting_processing", "attempt",
    "created_at", "started_at", "completed_at", "published_at",
}  # fmt: skip


@pytest.fixture
def settings(monkeypatch) -> Settings:
    configured = Settings(**{**get_settings().model_dump(), "youtube_publishing_enabled": True,
                             "publishing_token_encryption_key": KEY,
                             "google_client_id": "x.apps.googleusercontent.com",
                             "google_client_secret": "s",
                             "google_oauth_redirect_uri":
                                 "http://localhost:8000/publishing/youtube/callback"})  # fmt: skip
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


@pytest.fixture
def storage(tmp_path):
    local = LocalStorageProvider(tmp_path / "media")
    app.dependency_overrides[get_storage] = lambda: local
    yield local
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def queue(monkeypatch):
    queued: list[tuple[uuid.UUID, str]] = []

    def enqueue(job_id, *, task_id):
        queued.append((job_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_publish", enqueue)
    return queued


@pytest.fixture
def world(client: TestClient, db_session: Session, storage, settings, queue):
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(DATA), edit.storage_key)
    connection = connect(db_session, user)
    sign_in(client, user.id)
    return {"user": user, "edit": edit, "connection": connection,
            "panel": f"/edits/{edit.id}/publish"}  # fmt: skip


def sign_in(client: TestClient, user_id) -> None:
    client.cookies.clear()
    client.cookies.set(get_settings().auth_cookie_name, create_access_token(user_id))


def run_pipeline(job_id, db, settings, storage, provider, task_id):
    return pipeline.publish_short(job_id, db, settings=settings, storage=storage,
                                  provider=provider, task_id=task_id,
                                  sleep=lambda s: None)  # fmt: skip


# --- the panel -----


def test_the_panel_offers_private_prefill_from_the_candidate(client, world):
    panel = client.get(world["panel"]).json()
    assert panel["enabled"] is True and panel["edit_ready"] is True
    assert panel["connection"]["status"] == "connected"
    assert panel["defaults"] == {"title": "Moment", "description": "h", "tags": [],
                                 "privacy": "private", "made_for_kids": False}  # fmt: skip
    assert panel["jobs"] == []


def test_everything_is_owner_scoped(client, db_session, world):
    other, _ = ready_edit(db_session)
    job = client.post(world["panel"], json=BODY).json()
    sign_in(client, other.id)
    assert client.get(world["panel"]).status_code == 404
    assert client.post(world["panel"], json=BODY).status_code == 404
    assert client.get(f"/publish-jobs/{job['id']}").status_code == 404
    assert client.post(f"/publish-jobs/{job['id']}/retry").status_code == 404
    client.cookies.clear()
    for method, url in (("GET", world["panel"]), ("POST", world["panel"]),
                        ("GET", f"/publish-jobs/{job['id']}")):  # fmt: skip
        assert client.request(method, url, json=BODY).status_code == 401


# --- publishing -----


def test_publishing_creates_one_queued_private_job(client, db_session, world, queue):
    response = client.post(world["panel"], json=BODY)

    assert response.status_code == 201
    job = response.json()
    assert set(job) == PUBLIC_FIELDS
    assert job["status"] == "queued" and job["privacy"] == "private"
    assert job["tags"] == ["clips"] and job["retryable"] is False and job["video_url"] is None
    row = db_session.get(PublishJob, uuid.UUID(job["id"]))
    assert queue == [(row.id, row.celery_task_id)]
    for secret in (row.celery_task_id, world["edit"].storage_key):
        assert secret not in response.text

    again = client.post(world["panel"], json=BODY)
    assert again.status_code == 200 and again.json()["id"] == job["id"] and len(queue) == 1
    changed = client.post(world["panel"], json={**BODY, "privacy": "unlisted"})
    assert changed.status_code == 201 and changed.json()["id"] != job["id"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"title": "x" * 101}, "title"),
        ({"title": "<b>"}, "title"),
        ({"title": "ok", "tags": ["a,b"]}, "tags"),
        ({"title": "ok", "privacy": "friends"}, "privacy"),
        ({"title": "ok", "description": "é" * 2501}, "description"),
    ],  # fmt: skip
)
def test_metadata_breaking_youtube_rules_is_a_422_naming_the_field(client, world, body, field):
    response = client.post(world["panel"], json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]


def test_publishing_needs_an_enabled_server(client, world, monkeypatch, settings):
    disabled = settings.model_copy(update={"youtube_publishing_enabled": False})
    monkeypatch.setattr(api, "get_settings", lambda: disabled)
    refused = client.post(world["panel"], json=BODY)
    assert refused.status_code == 409 and "not enabled" in refused.json()["detail"]
    assert client.get(world["panel"]).json()["enabled"] is False


def test_publishing_needs_a_working_connection(client, db_session, world):
    world["connection"].status = ConnectionStatus.NEEDS_RECONNECT
    db_session.commit()
    assert "Reconnect" in client.post(world["panel"], json=BODY).json()["detail"]
    db_session.delete(world["connection"])
    db_session.commit()
    assert "Connect a YouTube" in client.post(world["panel"], json=BODY).json()["detail"]


def test_publishing_needs_the_rendered_file(client, world, storage):
    storage.delete(world["edit"].storage_key)
    response = client.post(world["panel"], json=BODY)
    assert response.status_code == 409 and "Render the short" in response.json()["detail"]
    assert client.get(world["panel"]).json()["edit_ready"] is False


def test_a_queue_outage_leaves_no_job(client, db_session, world, monkeypatch):
    def down(job_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_publish", down)
    assert client.post(world["panel"], json=BODY).status_code == 503
    assert db_session.scalar(select(PublishJob)) is None


# --- following and retrying -----


def test_progress_and_links_follow_the_pipeline(client, db_session, world, storage, settings):
    job = client.post(world["panel"], json=BODY).json()
    row = db_session.get(PublishJob, uuid.UUID(job["id"]))
    run_pipeline(row.id, db_session, settings, storage, FakePublishingProvider(),
                 row.celery_task_id)  # fmt: skip

    done = client.get(f"/publish-jobs/{job['id']}").json()
    assert done["status"] == "uploaded" and done["progress_percent"] == 100
    assert done["bytes_uploaded"] == done["bytes_total"] == len(DATA)
    assert done["simulated"] is True and done["video_url"] is None  # never a fake link
    assert done["retryable"] is False

    row.provider_video_id = "dQw4w9WgXcQ"  # as a real YouTube upload would record it
    db_session.commit()
    real = client.get(f"/publish-jobs/{job['id']}").json()
    assert real["video_url"] == "https://youtu.be/dQw4w9WgXcQ" and real["simulated"] is False
    assert real["studio_url"] == "https://studio.youtube.com/video/dQw4w9WgXcQ/edit"
    assert [j["id"] for j in client.get(world["panel"]).json()["jobs"]] == [job["id"]]


def test_only_a_job_that_failed_before_upload_can_be_retried(
    client, db_session, world, storage, settings, queue
):
    job = client.post(world["panel"], json=BODY).json()
    url = f"/publish-jobs/{job['id']}/retry"
    assert client.post(url).status_code == 409  # queued: nothing to retry

    row = db_session.get(PublishJob, uuid.UUID(job["id"]))
    provider = FakePublishingProvider()
    provider.fail("start_upload", [PublishErrorCode.RATE_LIMITED])
    run_pipeline(row.id, db_session, settings, storage, provider, row.celery_task_id)
    failed = client.get(f"/publish-jobs/{job['id']}").json()
    assert failed["status"] == "failed" and failed["retryable"] is True
    assert failed["error_message"] and "http" not in failed["error_message"].lower()

    old_task = row.celery_task_id
    retried = client.post(url)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert retried.json()["attempt"] == 2
    db_session.refresh(row)
    assert row.celery_task_id != old_task and queue[-1] == (row.id, row.celery_task_id)

    run_pipeline(row.id, db_session, settings, storage, provider, row.celery_task_id)
    assert client.get(f"/publish-jobs/{job['id']}").json()["status"] == "uploaded"
    refused = client.post(url)
    assert refused.status_code == 409 and "already on YouTube" in refused.json()["detail"]


def test_retries_are_bounded(client, db_session, world, settings):
    job = client.post(world["panel"], json=BODY).json()
    row = db_session.get(PublishJob, uuid.UUID(job["id"]))
    row.status, row.attempt = PublishStatus.FAILED, settings.publish_max_attempts
    db_session.commit()
    refused = client.post(f"/publish-jobs/{job['id']}/retry")
    assert refused.status_code == 409 and "too many times" in refused.json()["detail"]


def test_a_provider_failure_is_not_retried(client, db_session, world):
    job = client.post(world["panel"], json=BODY).json()
    row = db_session.get(PublishJob, uuid.UUID(job["id"]))
    row.status, row.provider_video_id = PublishStatus.PROVIDER_FAILED, "vid-rejected"
    db_session.commit()
    assert client.post(f"/publish-jobs/{job['id']}/retry").status_code == 409


def test_publishing_is_rate_limited(client, world, monkeypatch):
    from app.core import rate_limit
    from app.core.rate_limit import DEFAULT_LIMITS, Limit, RateLimiter

    class Memory:
        def __init__(self):
            self.counts = {}

        def hit(self, key, window):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

    limiter = RateLimiter(Memory(), {**DEFAULT_LIMITS, "publish_start": Limit(2, 3600)})
    monkeypatch.setattr(rate_limit, "get_limiter", lambda: limiter)
    codes = [client.post(world["panel"], json={**BODY, "title": f"T{n}"}).status_code
             for n in range(3)]  # fmt: skip
    assert codes == [201, 201, 429]
