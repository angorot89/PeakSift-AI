import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import transcriptions as api
from app.core.config import get_settings
from app.models import Transcription, TranscriptSegment, Video
from app.workers.dispatch import JobQueueUnavailable

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024

STATUS_KEYS = {
    "id",
    "video_id",
    "status",
    "provider",
    "model",
    "language",
    "language_probability",
    "progress_percent",
    "segment_count",
    "is_stale",
    "error_code",
    "error_message",
    "created_at",
    "started_at",
    "completed_at",
}


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch, db_session):
    """Never run the real pipeline; record what would be queued and prove the fencing token
    was committed on the row before the job was handed to the broker."""
    queued: list[uuid.UUID] = []

    def fake_enqueue(transcription_id, *, task_id):
        row = db_session.get(Transcription, transcription_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append(transcription_id)
        return task_id

    monkeypatch.setattr(api, "enqueue_transcription", fake_enqueue)
    return queued


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in Path(get_settings().media_root).rglob("*"):
        if path.is_file():
            path.unlink()


def sign_up(client: TestClient, email: str = "owner@example.com") -> None:
    assert (
        client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )


def ready_video(client: TestClient, db_session: Session) -> tuple[str, str]:
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    response = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", MP4_BYTES, "video/mp4")}
    )
    video_id = response.json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    video.status, video.error_message, video.duration_seconds = "ready", None, 120.0
    db_session.commit()
    return project_id, video_id


def base(project_id: str, video_id: str) -> str:
    return f"/projects/{project_id}/videos/{video_id}"


def complete_with_segments(db_session: Session, video_id: str, count: int) -> Transcription:
    transcription = db_session.get(Video, uuid.UUID(video_id)).transcription
    transcription.status = "completed"
    transcription.progress_percent = 100
    transcription.language = "en"
    transcription.full_text = " ".join(f"segment {i}" for i in range(count))
    for i in range(count):
        transcription.segments.append(
            TranscriptSegment(
                sequence_index=i, start_time=i * 2.0, end_time=i * 2.0 + 1.5, text=f"segment {i}"
            )
        )
    db_session.commit()
    return transcription


# --- authentication and ownership -----


def test_all_endpoints_require_authentication(client: TestClient):
    url = base(str(uuid.uuid4()), str(uuid.uuid4()))
    assert client.post(f"{url}/transcription").status_code == 401
    assert client.get(f"{url}/transcription").status_code == 401
    assert client.post(f"{url}/transcription/retry").status_code == 401
    assert client.get(f"{url}/transcript").status_code == 401


def test_other_user_cannot_reach_a_video(client: TestClient, db_session: Session):
    sign_up(client, "alice@example.com")
    project_id, video_id = ready_video(client, db_session)
    client.post(f"{base(project_id, video_id)}/transcription")
    client.cookies.clear()
    sign_up(client, "bob@example.com")

    url = base(project_id, video_id)
    assert client.post(f"{url}/transcription").status_code == 404
    assert client.get(f"{url}/transcription").status_code == 404
    # optional=true never turns another user's resource into a null answer
    assert client.get(f"{url}/transcription", params={"optional": "true"}).status_code == 404
    assert client.post(f"{url}/transcription/retry").status_code == 404
    assert client.get(f"{url}/transcript").status_code == 404


def test_video_must_belong_to_project_in_url(client: TestClient, db_session: Session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    other_project = client.post("/projects", json={"name": "Other"}).json()["id"]

    assert client.post(f"{base(other_project, video_id)}/transcription").status_code == 404
    assert client.get(f"{base(project_id, uuid.uuid4())}/transcription").status_code == 404


# --- start -----


def test_start_queues_a_job(client: TestClient, db_session: Session, fake_queue):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)

    response = client.post(f"{base(project_id, video_id)}/transcription")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_KEYS
    assert body["status"] == "queued" and body["progress_percent"] == 0
    assert body["segment_count"] == 0 and body["video_id"] == video_id
    assert (
        body["provider"] == "faster_whisper"
        and body["model"] == get_settings().faster_whisper_model
    )
    assert "celery_task_id" not in body and "audio_storage_key" not in body
    assert str(get_settings().media_root) not in response.text

    transcription = db_session.get(Transcription, uuid.UUID(body["id"]))
    assert fake_queue == [transcription.id]
    assert uuid.UUID(transcription.celery_task_id)  # pre-chosen, committed before enqueue


def test_start_is_idempotent_for_queued_running_and_completed(client, db_session, fake_queue):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    first = client.post(f"{base(project_id, video_id)}/transcription").json()

    for status in ("queued", "transcribing", "completed"):
        db_session.get(Transcription, uuid.UUID(first["id"])).status = status
        db_session.commit()
        again = client.post(f"{base(project_id, video_id)}/transcription")
        assert again.status_code == 200
        assert again.json()["id"] == first["id"] and again.json()["status"] == status

    assert len(fake_queue) == 1  # never re-queued, never a second paid job
    assert db_session.scalar(
        select(Transcription).where(Transcription.video_id == uuid.UUID(video_id))
    ).id == uuid.UUID(first["id"])


def test_start_refuses_video_that_is_not_ready(client, db_session, fake_queue):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    db_session.get(Video, uuid.UUID(video_id)).status = "failed"
    db_session.commit()

    response = client.post(f"{base(project_id, video_id)}/transcription")

    assert response.status_code == 409 and fake_queue == []


def test_start_after_failure_points_to_retry(client, db_session, fake_queue):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    db_session.get(Transcription, uuid.UUID(created["id"])).status = "failed"
    db_session.commit()

    response = client.post(f"{base(project_id, video_id)}/transcription")

    assert response.status_code == 409 and "retry" in response.json()["detail"]
    assert len(fake_queue) == 1


def test_queue_outage_leaves_no_orphan_row(client, db_session, monkeypatch):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)

    def down(transcription_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_transcription", down)

    response = client.post(f"{base(project_id, video_id)}/transcription")

    assert response.status_code == 503
    assert db_session.scalar(select(Transcription)) is None
    assert client.get(f"{base(project_id, video_id)}/transcription").status_code == 404


# --- status -----


def test_status_404_before_start(client, db_session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)

    assert client.get(f"{base(project_id, video_id)}/transcription").status_code == 404


def test_status_reports_progress_and_segment_count(client, db_session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    client.post(f"{base(project_id, video_id)}/transcription")
    complete_with_segments(db_session, video_id, 7)

    body = client.get(f"{base(project_id, video_id)}/transcription").json()

    assert body["status"] == "completed" and body["progress_percent"] == 100
    assert body["segment_count"] == 7 and body["language"] == "en"
    assert "full_text" not in body  # polling response stays small


def test_status_exposes_safe_failure_fields_only(client, db_session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    t = db_session.get(Transcription, uuid.UUID(created["id"]))
    t.status, t.error_code, t.error_message = (
        "failed",
        "no_audio_stream",
        "The video has no audio track",
    )
    t.audio_storage_key = f"transcription/{t.id}/normalized.mp3"
    db_session.commit()

    response = client.get(f"{base(project_id, video_id)}/transcription")

    assert response.json()["error_code"] == "no_audio_stream"
    assert response.json()["error_message"] == "The video has no audio track"
    assert "normalized.mp3" not in response.text and "task-" not in response.text


# --- retry -----


def test_retry_requeues_a_failed_job(client, db_session, fake_queue):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    t = db_session.get(Transcription, uuid.UUID(created["id"]))
    t.status, t.error_code, t.error_message, t.progress_percent = "failed", "x", "boom", 40
    db_session.commit()

    response = client.post(f"{base(project_id, video_id)}/transcription/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"] and body["status"] == "queued"
    assert (
        body["progress_percent"] == 0
        and body["error_code"] is None
        and body["error_message"] is None
    )
    assert len(fake_queue) == 2 and uuid.UUID(t.celery_task_id)


@pytest.mark.parametrize("status", ["queued", "extracting_audio", "transcribing", "completed"])
def test_retry_refused_unless_failed(client, db_session, fake_queue, status):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    db_session.get(Transcription, uuid.UUID(created["id"])).status = status
    db_session.commit()

    assert client.post(f"{base(project_id, video_id)}/transcription/retry").status_code == 409
    assert len(fake_queue) == 1


def test_retry_404_without_transcription(client, db_session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)

    assert client.post(f"{base(project_id, video_id)}/transcription/retry").status_code == 404


# --- transcript -----


def test_transcript_404_without_transcription(client, db_session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)

    assert client.get(f"{base(project_id, video_id)}/transcript").status_code == 404


@pytest.mark.parametrize("status", ["queued", "extracting_audio", "transcribing", "failed"])
def test_transcript_hidden_until_completed(client, db_session, status):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    t = db_session.get(Transcription, uuid.UUID(created["id"]))
    t.status = status
    t.segments.append(TranscriptSegment(sequence_index=0, start_time=0, end_time=1, text="partial"))
    db_session.commit()

    response = client.get(f"{base(project_id, video_id)}/transcript")

    assert response.status_code == 409 and status in response.json()["detail"]
    assert "partial" not in response.text


def test_transcript_pages_in_sequence_order(client, db_session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    client.post(f"{base(project_id, video_id)}/transcription")
    complete_with_segments(db_session, video_id, 12)
    url = f"{base(project_id, video_id)}/transcript"

    first = client.get(url, params={"offset": 0, "limit": 5}).json()
    assert first["total"] == 12 and first["offset"] == 0 and first["limit"] == 5
    assert [s["sequence_index"] for s in first["segments"]] == [0, 1, 2, 3, 4]
    assert first["segments"][1] == {
        "sequence_index": 1,
        "start": 2.0,
        "end": 3.5,
        "text": "segment 1",
        "speaker": None,
    }
    assert first["full_text"] is None

    last = client.get(url, params={"offset": 10, "limit": 5}).json()
    assert [s["sequence_index"] for s in last["segments"]] == [10, 11]

    beyond = client.get(url, params={"offset": 50, "limit": 5}).json()
    assert beyond["segments"] == [] and beyond["total"] == 12


def test_transcript_default_page_and_full_text_on_request(client, db_session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    client.post(f"{base(project_id, video_id)}/transcription")
    complete_with_segments(db_session, video_id, 3)
    url = f"{base(project_id, video_id)}/transcript"

    default = client.get(url).json()
    assert default["limit"] == 200 and len(default["segments"]) == 3

    with_text = client.get(url, params={"include_text": "true"}).json()
    assert with_text["full_text"] == "segment 0 segment 1 segment 2"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_transcript_pagination_bounds(client, db_session, params):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    client.post(f"{base(project_id, video_id)}/transcription")
    complete_with_segments(db_session, video_id, 1)

    assert client.get(f"{base(project_id, video_id)}/transcript", params=params).status_code == 422


# --- hardening: stale jobs -----


def test_status_flags_a_stale_job(client, db_session):
    from datetime import UTC, datetime, timedelta

    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    assert client.get(f"{base(project_id, video_id)}/transcription").json()["is_stale"] is False

    t = db_session.get(Transcription, uuid.UUID(created["id"]))
    t.status, t.heartbeat_at = "transcribing", datetime.now(UTC) - timedelta(hours=3)
    db_session.commit()

    body = client.get(f"{base(project_id, video_id)}/transcription").json()
    assert body["status"] == "transcribing" and body["is_stale"] is True


def test_retry_resets_a_stale_job(client, db_session, fake_queue):
    from datetime import UTC, datetime, timedelta

    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    t = db_session.get(Transcription, uuid.UUID(created["id"]))
    t.status, t.heartbeat_at, t.progress_percent = (
        "extracting_audio",
        datetime.now(UTC) - timedelta(hours=3),
        5,
    )
    db_session.commit()

    response = client.post(f"{base(project_id, video_id)}/transcription/retry")

    assert response.status_code == 200
    assert response.json()["status"] == "queued" and response.json()["is_stale"] is False
    assert len(fake_queue) == 2 and uuid.UUID(t.celery_task_id)


def test_retry_refuses_a_live_job_with_fresh_heartbeat(client, db_session, fake_queue):
    from datetime import UTC, datetime

    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    t = db_session.get(Transcription, uuid.UUID(created["id"]))
    t.status, t.heartbeat_at = "transcribing", datetime.now(UTC)
    db_session.commit()

    assert client.post(f"{base(project_id, video_id)}/transcription/retry").status_code == 409
    assert len(fake_queue) == 1


def test_retry_issues_a_new_token_committed_before_enqueue(client, db_session, fake_queue):
    """The V0.3 flow stored the new task id *after* enqueueing, so a fast worker could start
    while the row still held the previous attempt's token. Now the token comes first."""
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    row = db_session.get(Transcription, uuid.UUID(created["id"]))
    first_token = row.celery_task_id
    row.status = "failed"
    db_session.commit()

    assert client.post(f"{base(project_id, video_id)}/transcription/retry").status_code == 200

    db_session.refresh(row)
    assert row.celery_task_id != first_token and uuid.UUID(row.celery_task_id)
    assert len(fake_queue) == 2  # fake_queue asserted the token was already on the row


def test_retry_when_queue_is_down_marks_the_job_failed(client, db_session, monkeypatch):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    created = client.post(f"{base(project_id, video_id)}/transcription").json()
    db_session.get(Transcription, uuid.UUID(created["id"])).status = "failed"
    db_session.commit()

    def down(transcription_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_transcription", down)
    assert client.post(f"{base(project_id, video_id)}/transcription/retry").status_code == 503
    body = client.get(f"{base(project_id, video_id)}/transcription").json()
    assert body["status"] == "failed" and body["error_code"] == "queue_unavailable"


def test_no_transcription_yet_is_null_when_optional(client: TestClient, db_session: Session):
    sign_up(client)
    project_id, video_id = ready_video(client, db_session)
    url = f"{base(project_id, video_id)}/transcription"
    assert client.get(url).status_code == 404
    response = client.get(url, params={"optional": "true"})
    assert response.status_code == 200 and response.json() is None
    client.post(url)
    assert client.get(url, params={"optional": "true"}).json()["status"] == "queued"
