"""Scheduled publishing: a post waits for its time, the scheduler releases it, and the creator
can move it, release it or cancel it while it waits."""

import io
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import publish_jobs as api
from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.main import app
from app.models import ClipEditStatus, ConnectionStatus, PublishJob, PublishStatus
from app.services import shorts_library
from app.services.publishing import schedule
from app.services.storage import LocalStorageProvider
from app.workers.dispatch import JobQueueUnavailable
from tests.publishing_fixtures import KEY, connect, ready_edit

DATA = b"x" * 4096
BODY = {"title": "My short", "description": "", "tags": ["clips"]}


def later(**delta) -> datetime:
    return (datetime.now(UTC) + timedelta(**(delta or {"hours": 3}))).replace(microsecond=0)


def iso(when: datetime) -> str:
    return when.isoformat()


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


def sign_in(client: TestClient, user_id) -> None:
    client.cookies.clear()
    client.cookies.set(get_settings().auth_cookie_name, create_access_token(user_id))


@pytest.fixture
def world(client: TestClient, db_session: Session, storage, settings, queue):
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(DATA), edit.storage_key)
    connection = connect(db_session, user)
    sign_in(client, user.id)
    return {"user": user, "edit": edit, "connection": connection,
            "panel": f"/edits/{edit.id}/publish"}  # fmt: skip


def schedule_post(client, world, when: datetime | None = None, **body) -> dict:
    response = client.post(
        world["panel"], json={**BODY, **body, "scheduled_at": iso(when or later())}
    )
    assert response.status_code == 201, response.text
    return response.json()


def row(db_session: Session, job: dict) -> PublishJob:
    return db_session.get(PublishJob, uuid.UUID(job["id"]))


def count(db_session: Session) -> int:
    return db_session.scalar(select(func.count()).select_from(PublishJob)) or 0


# --- scheduling ---------------------------------------------------------------------------


def test_a_scheduled_post_waits_and_is_not_queued(client, db_session, world, queue):
    when = later(days=2)

    job = schedule_post(client, world, when)

    assert job["status"] == "scheduled" and job["retryable"] is False
    assert datetime.fromisoformat(job["scheduled_at"]) == when
    assert queue == []  # nothing is uploaded until its time
    stored = row(db_session, job)
    assert stored.celery_task_id is None and stored.scheduled_at == when

    # The same request again is the same post; with a new time it moves.
    moved_to = later(days=3)
    again = client.post(world["panel"], json={**BODY, "scheduled_at": iso(moved_to)})
    assert again.status_code == 200 and again.json()["id"] == job["id"]
    assert datetime.fromisoformat(again.json()["scheduled_at"]) == moved_to
    assert count(db_session) == 1 and queue == []


def test_times_are_stored_in_utc_whatever_zone_was_sent(client, db_session, world):
    casablanca = later(days=1).astimezone(timezone(timedelta(hours=1)))

    job = schedule_post(client, world, casablanca)

    assert row(db_session, job).scheduled_at == casablanca.astimezone(UTC)


@pytest.mark.parametrize(
    "when",
    [
        lambda: iso(datetime.now(UTC) - timedelta(hours=1)),  # in the past
        lambda: iso(datetime.now(UTC) + timedelta(seconds=30)),  # too soon: that is "now"
        lambda: iso(datetime.now(UTC) + timedelta(days=500)),  # too far
        lambda: (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat(),  # no zone
    ],
)
def test_unusable_times_are_refused_and_name_the_field(client, db_session, world, when, queue):
    response = client.post(world["panel"], json={**BODY, "scheduled_at": when()})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "scheduled_at"]
    assert count(db_session) == 0 and queue == []


def test_one_short_has_one_waiting_post(client, db_session, world):
    first = schedule_post(client, world)

    second = client.post(
        world["panel"], json={**BODY, "title": "Another title", "scheduled_at": iso(later())}
    )
    now = client.post(world["panel"], json={**BODY, "title": "Published right away"})

    assert second.status_code == 409 and "already scheduled" in second.json()["detail"]
    assert now.status_code == 409  # publish it now from the calendar, not as a second post
    assert [j.id for j in db_session.scalars(select(PublishJob))] == [uuid.UUID(first["id"])]


def test_scheduling_needs_what_publishing_needs(client, db_session, world):
    world["connection"].status = ConnectionStatus.NEEDS_RECONNECT
    db_session.commit()

    response = client.post(world["panel"], json={**BODY, "scheduled_at": iso(later())})

    assert response.status_code == 409 and count(db_session) == 0


# --- moving, releasing and cancelling -----------------------------------------------------


def test_a_waiting_post_can_be_moved(client, db_session, world):
    job = schedule_post(client, world)
    when = later(days=5)

    moved = client.patch(f"/publish-jobs/{job['id']}/schedule", json={"scheduled_at": iso(when)})

    assert moved.status_code == 200 and row(db_session, job).scheduled_at == when
    past = client.patch(
        f"/publish-jobs/{job['id']}/schedule",
        json={"scheduled_at": iso(datetime.now(UTC) - timedelta(days=1))},
    )
    assert past.status_code == 422 and row(db_session, job).scheduled_at == when


def test_publish_now_releases_a_waiting_post(client, db_session, world, queue):
    job = schedule_post(client, world)

    released = client.post(f"/publish-jobs/{job['id']}/publish-now")

    assert released.status_code == 200 and released.json()["status"] == "queued"
    stored = row(db_session, job)
    assert queue == [(stored.id, stored.celery_task_id)] and stored.celery_task_id
    # It is no longer waiting: every schedule action now answers 409.
    for call in (
        lambda: client.post(f"/publish-jobs/{job['id']}/publish-now"),
        lambda: client.patch(
            f"/publish-jobs/{job['id']}/schedule", json={"scheduled_at": iso(later())}
        ),
        lambda: client.delete(f"/publish-jobs/{job['id']}"),
    ):
        assert call().status_code == 409
    assert count(db_session) == 1 and len(queue) == 1


def test_publish_now_with_the_queue_down_keeps_the_post_scheduled(
    client, db_session, world, monkeypatch
):
    job = schedule_post(client, world)

    def down(job_id, *, task_id):
        raise JobQueueUnavailable("broker down")

    monkeypatch.setattr(api, "enqueue_publish", down)

    assert client.post(f"/publish-jobs/{job['id']}/publish-now").status_code == 503
    stored = row(db_session, job)
    assert stored.status == PublishStatus.SCHEDULED and stored.celery_task_id is None


def test_cancelling_removes_only_a_waiting_post(client, db_session, world, queue):
    job = schedule_post(client, world)

    assert client.delete(f"/publish-jobs/{job['id']}").status_code == 204
    assert count(db_session) == 0 and queue == []

    published = client.post(world["panel"], json=BODY).json()  # an ordinary publish
    assert client.delete(f"/publish-jobs/{published['id']}").status_code == 409
    assert count(db_session) == 1


def test_schedule_actions_are_owner_scoped(client, db_session, world):
    job = schedule_post(client, world)
    client.cookies.clear()
    registered = client.post(
        "/auth/register", json={"email": "other@example.com", "password": "correct horse battery"}
    )
    assert registered.status_code == 201

    assert client.delete(f"/publish-jobs/{job['id']}").status_code == 404
    assert client.post(f"/publish-jobs/{job['id']}/publish-now").status_code == 404
    assert (
        client.patch(
            f"/publish-jobs/{job['id']}/schedule", json={"scheduled_at": iso(later())}
        ).status_code
        == 404
    )
    start, end = iso(datetime.now(UTC) - timedelta(days=1)), iso(later(days=7))
    assert client.get("/publish-jobs", params={"from": start, "to": end}).json()["items"] == []
    assert row(db_session, job).status == PublishStatus.SCHEDULED


# --- the scheduler ------------------------------------------------------------------------


def release(db_session, settings, *, now=None, enqueue=None):
    sent: list[tuple[uuid.UUID, str]] = []

    def record(job_id, *, task_id):
        sent.append((job_id, task_id))

    released = schedule.release_due(db_session, settings, enqueue or record, now=now)
    return released, sent


def test_only_due_posts_are_released_once(client, db_session, world, settings):
    job = schedule_post(client, world, later(hours=1))
    stored = row(db_session, job)

    assert release(db_session, settings) == ([], [])  # not yet
    assert stored.status == PublishStatus.SCHEDULED

    at_time = stored.scheduled_at + timedelta(seconds=20)
    released, sent = release(db_session, settings, now=at_time)

    assert released == [stored.id] and sent == [(stored.id, stored.celery_task_id)]
    assert stored.status == PublishStatus.QUEUED and stored.celery_task_id
    assert stored.scheduled_at is not None  # kept: the calendar still shows when it was meant
    assert release(db_session, settings, now=at_time) == ([], [])  # never twice


def test_a_post_missed_by_an_outage_is_not_published_late(client, db_session, world, settings):
    job = schedule_post(client, world, later(hours=1))
    stored = row(db_session, job)
    much_later = stored.scheduled_at + timedelta(
        seconds=settings.publish_schedule_grace_seconds + 60
    )

    released, sent = release(db_session, settings, now=much_later)

    assert released == [] and sent == []
    assert (stored.status, stored.error_code) == (PublishStatus.FAILED, "schedule_missed")
    assert (
        client.get(f"/publish-jobs/{job['id']}").json()["retryable"] is True
    )  # the creator decides


def test_a_post_a_little_late_still_goes_out(client, db_session, world, settings):
    job = schedule_post(client, world, later(hours=1))
    stored = row(db_session, job)

    released, _ = release(db_session, settings, now=stored.scheduled_at + timedelta(minutes=20))

    assert released == [stored.id]


def test_a_post_fails_with_the_reason_when_it_cannot_go_out(client, db_session, world, settings):
    job = schedule_post(client, world, later(hours=1))
    stored = row(db_session, job)
    world["connection"].status = ConnectionStatus.NEEDS_RECONNECT
    db_session.commit()

    released, sent = release(db_session, settings, now=stored.scheduled_at)

    assert released == [] and sent == []
    assert (stored.status, stored.error_code) == (PublishStatus.FAILED, "needs_reconnect")
    assert "Reconnect" in stored.error_message


def test_a_short_that_is_no_longer_ready_is_not_uploaded(client, db_session, world, settings):
    job = schedule_post(client, world, later(hours=1))
    stored = row(db_session, job)
    world["edit"].status = ClipEditStatus.FAILED
    db_session.commit()

    release(db_session, settings, now=stored.scheduled_at)

    assert (stored.status, stored.error_code) == (PublishStatus.FAILED, "edit_not_ready")


def test_a_busy_queue_leaves_the_post_scheduled_for_the_next_tick(
    client, db_session, world, settings
):
    job = schedule_post(client, world, later(hours=1))
    stored = row(db_session, job)

    def down(job_id, *, task_id):
        raise JobQueueUnavailable("broker down")

    released, _ = release(db_session, settings, now=stored.scheduled_at, enqueue=down)
    assert released == [] and stored.status == PublishStatus.SCHEDULED

    released, _ = release(db_session, settings, now=stored.scheduled_at + timedelta(minutes=1))
    assert released == [stored.id]


# --- the calendar and the library ---------------------------------------------------------


def test_the_calendar_lists_posts_in_range_at_their_time(client, db_session, world):
    when = later(days=2)
    job = schedule_post(client, world, when)

    def calendar(start: datetime, end: datetime):
        return client.get("/publish-jobs", params={"from": iso(start), "to": iso(end)})

    body = calendar(when - timedelta(days=1), when + timedelta(days=1)).json()
    assert body["connection_ready"] is True
    (item,) = body["items"]
    assert item["job"]["id"] == job["id"] and item["job"]["status"] == "scheduled"
    assert datetime.fromisoformat(item["at"]) == when
    assert item["short_title"] and item["project_name"]
    assert uuid.UUID(item["project_id"]) and uuid.UUID(item["clip_id"])

    assert calendar(when + timedelta(days=1), when + timedelta(days=2)).json()["items"] == []
    assert calendar(when, when + timedelta(days=90)).status_code == 422  # too wide
    assert calendar(when, when).status_code == 422  # empty
    naive = client.get(
        "/publish-jobs", params={"from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00"}
    )
    assert naive.status_code == 422


def test_a_waiting_post_does_not_change_what_happened_on_youtube(
    client, db_session, world, settings
):
    job = schedule_post(client, world)
    stored = row(db_session, job)

    waiting = shorts_library.publication([stored], settings)
    assert waiting.state == shorts_library.PublishState.NOT_PUBLISHED and waiting.job is None
    status, reason = shorts_library.short_status(world["edit"], waiting, settings)
    assert (status, reason) == (shorts_library.ShortStatus.READY, None)


def test_validate_time_rounds_to_the_second_in_utc():
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    when = datetime(2026, 11, 27, 9, 30, 15, 987654, tzinfo=UTC)
    assert schedule.validate_time(when, now) == datetime(2026, 11, 27, 9, 30, 15, tzinfo=UTC)
    with pytest.raises(schedule.ScheduleError):
        schedule.validate_time(now + timedelta(minutes=1), now)
