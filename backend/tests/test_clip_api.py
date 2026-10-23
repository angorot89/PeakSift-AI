import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import clip_detection as detection_api
from app.api import clips as api
from app.core.config import Settings, get_settings
from app.models import Clip, ClipCandidate, ClipDetectionRun, TranscriptSegment, Video
from app.services.clip_render.storage import ClipArtifactStore
from app.services.storage import LocalStorageProvider
from app.workers.dispatch import JobQueueUnavailable

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024

CLIP_KEYS = {
    "id",
    "candidate_id",
    "run_id",
    "video_id",
    "title",
    "status",
    "progress_percent",
    "attempt",
    "is_stale",
    "start_time",
    "end_time",
    "duration_seconds",
    "render_profile",
    "content_type",
    "file_size",
    "width",
    "height",
    "fps",
    "video_codec",
    "audio_codec",
    "error_code",
    "error_message",
    "created_at",
    "started_at",
    "completed_at",
}


@pytest.fixture(autouse=True)
def fake_queues(monkeypatch, db_session):
    """Never run real pipelines; prove the render task id is committed before enqueue."""
    rendered: list[tuple[uuid.UUID, str]] = []

    def fake_render_enqueue(clip_id, *, task_id):
        row = db_session.get(Clip, clip_id)
        assert row is not None and row.celery_task_id == task_id
        rendered.append((clip_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_clip_render", fake_render_enqueue)
    monkeypatch.setattr(detection_api, "enqueue_clip_detection", lambda run_id, *, task_id: task_id)
    return rendered


@pytest.fixture
def settings(monkeypatch) -> Settings:
    base = get_settings().model_dump()
    base["openai_api_key"] = None
    settings = Settings(**base)
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(detection_api, "get_settings", lambda: settings)
    return settings


def sign_up(client: TestClient, email: str = "owner@example.com") -> None:
    assert (
        client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )


def candidate_setup(client: TestClient, db_session: Session, *, candidates: int = 2) -> dict:
    """Owner-scoped ready video (300 s) with a completed run holding `candidates` candidates."""
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    video_id = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", MP4_BYTES, "video/mp4")}
    ).json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    video.status, video.error_message, video.duration_seconds = "ready", None, 300.0
    db_session.commit()
    assert client.post(f"/projects/{project_id}/videos/{video_id}/transcription").status_code == 200
    transcription = video.transcription
    transcription.status, transcription.progress_percent, transcription.language = (
        "completed",
        100,
        "en",
    )
    for i in range(60):
        transcription.segments.append(
            TranscriptSegment(
                sequence_index=i, start_time=i * 5.0, end_time=(i + 1) * 5.0, text=f"line {i}"
            )
        )
    db_session.commit()
    run_id = client.post(
        f"/projects/{project_id}/videos/{video_id}/clip-detection", json={"provider": "ollama"}
    ).json()["id"]
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    run.status, run.progress_percent, run.windows_total, run.windows_done = "completed", 100, 1, 1
    for rank in range(1, candidates + 1):
        start = rank * 30.0
        run.candidates.append(
            ClipCandidate(
                video_id=run.video_id,
                start_time=start,
                end_time=start + 20.0,
                duration_seconds=20.0,
                title=f"Moment {rank}",
                hook="Hook",
                rationale="Because.",
                category="story",
                transcript_excerpt="line",
                overall_score=90 - rank,
                hook_score=90,
                entertainment_score=80,
                clarity_score=70,
                payoff_score=60,
                completeness_score=50,
                rank=rank,
            )
        )
    db_session.commit()
    ids = [str(c.id) for c in run.candidates]
    return {"project_id": project_id, "video_id": video_id, "run_id": run_id, "candidates": ids}


def clip_url(ctx: dict, index: int = 0) -> str:
    return (
        f"/projects/{ctx['project_id']}/videos/{ctx['video_id']}/clip-detection/{ctx['run_id']}"
        f"/candidates/{ctx['candidates'][index]}/clip"
    )


def clips_url(ctx: dict) -> str:
    return f"/projects/{ctx['project_id']}/videos/{ctx['video_id']}/clips"


def mark_ready(db_session: Session, clip: Clip) -> None:
    """A ready clip always has its file: write a small one at the final key."""
    store = ClipArtifactStore(LocalStorageProvider(Path(get_settings().media_root)))
    store.temp_path(clip.id).write_bytes(b"\x00" * 64)
    clip.storage_key = store.finalize(clip.id)
    clip.status, clip.progress_percent = "ready", 100
    db_session.commit()


# --- authentication and ownership -----


def test_all_endpoints_require_authentication(client: TestClient):
    ids = [str(uuid.uuid4()) for _ in range(4)]
    url = f"/projects/{ids[0]}/videos/{ids[1]}/clip-detection/{ids[2]}/candidates/{ids[3]}/clip"
    assert client.post(url).status_code == 401
    assert client.get(url).status_code == 401
    assert client.post(f"{url}/retry").status_code == 401
    assert client.get(f"/projects/{ids[0]}/videos/{ids[1]}/clips").status_code == 401


def test_other_user_gets_404_everywhere(client, db_session, settings):
    sign_up(client, "alice@example.com")
    ctx = candidate_setup(client, db_session)
    assert client.post(clip_url(ctx)).status_code == 201
    client.cookies.clear()
    sign_up(client, "bob@example.com")

    assert client.post(clip_url(ctx)).status_code == 404
    assert client.get(clip_url(ctx)).status_code == 404
    assert client.post(f"{clip_url(ctx)}/retry").status_code == 404
    assert client.get(clips_url(ctx)).status_code == 404


def test_unknown_candidate_or_wrong_run_is_404(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    other = candidate_setup(client, db_session)
    base = clip_url(ctx).rsplit("/candidates/", 1)[0] + "/candidates"
    assert client.post(f"{base}/{uuid.uuid4()}/clip").status_code == 404
    # A real candidate, but reached through another video's run: not found.
    assert client.post(f"{base}/{other['candidates'][0]}/clip").status_code == 404


# --- generate -----


def test_generate_creates_a_queued_clip_from_the_candidate_snapshot(
    client, db_session, settings, fake_queues
):
    sign_up(client)
    ctx = candidate_setup(client, db_session)

    response = client.post(clip_url(ctx))

    assert response.status_code == 201
    data = response.json()
    assert set(data) == CLIP_KEYS
    assert data["status"] == "queued" and data["progress_percent"] == 0 and data["attempt"] == 1
    assert (data["start_time"], data["end_time"], data["duration_seconds"]) == (30.0, 50.0, 20.0)
    assert data["title"] == "Moment 1" and data["run_id"] == ctx["run_id"]
    assert data["render_profile"] == "source_mp4_v1" and data["content_type"] == "video/mp4"
    assert data["is_stale"] is False and data["file_size"] is None
    assert "storage_key" not in data and "celery_task_id" not in data
    clip = db_session.get(Clip, uuid.UUID(data["id"]))
    assert fake_queues == [(clip.id, clip.celery_task_id)]


def test_generate_ignores_any_body_timestamps(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    response = client.post(clip_url(ctx), json={"start_time": 0, "end_time": 299})
    assert response.status_code == 201
    assert (response.json()["start_time"], response.json()["end_time"]) == (30.0, 50.0)


def test_duplicate_generate_returns_the_existing_clip(client, db_session, settings, fake_queues):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    first = client.post(clip_url(ctx))
    second = client.post(clip_url(ctx))
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(fake_queues) == 1  # one job, one row, one (future) file
    assert (
        db_session.scalar(
            __import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(Clip)
        )
        == 1
    )


def test_generate_on_a_ready_clip_returns_it_unchanged(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    clip.file_size = 4096
    clip.width, clip.height, clip.fps, clip.video_codec, clip.audio_codec = (
        640,
        360,
        25.0,
        "h264",
        "aac",
    )
    mark_ready(db_session, clip)

    response = client.post(clip_url(ctx))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready" and data["file_size"] == 4096 and data["width"] == 640
    assert "clips/" not in response.text  # storage key never leaks


def test_generate_on_a_failed_clip_requires_retry(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    db_session.get(Clip, uuid.UUID(clip_id)).status = "failed"
    db_session.commit()
    response = client.post(clip_url(ctx))
    assert response.status_code == 409 and "retry" in response.json()["detail"]


def test_dismissed_candidate_cannot_be_rendered_until_restored(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    candidate_base = clip_url(ctx).removesuffix("/clip")
    assert client.post(f"{candidate_base}/dismiss").status_code == 200

    response = client.post(clip_url(ctx))
    assert response.status_code == 409 and "Restore" in response.json()["detail"]

    assert client.post(f"{candidate_base}/reset").status_code == 200
    assert client.post(clip_url(ctx)).status_code == 201


def test_existing_clip_survives_a_later_dismissal(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    assert client.post(f"{clip_url(ctx).removesuffix('/clip')}/dismiss").status_code == 200
    response = client.get(clip_url(ctx))
    assert response.status_code == 200 and response.json()["id"] == clip_id


def test_generate_requires_a_ready_video(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    db_session.get(Video, uuid.UUID(ctx["video_id"])).status = "failed"
    db_session.commit()
    assert client.post(clip_url(ctx)).status_code == 409


def test_generate_revalidates_candidate_boundaries_against_the_source(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    video = db_session.get(Video, uuid.UUID(ctx["video_id"]))
    video.duration_seconds = 40.0  # the candidate [30, 50] now ends after the source
    db_session.commit()
    response = client.post(clip_url(ctx))
    assert response.status_code == 409 and "ends after the end" in response.json()["detail"]
    assert client.get(clip_url(ctx)).status_code == 404  # nothing was created


def test_concurrent_generate_race_returns_the_winner(client, db_session, settings, monkeypatch):
    """Two requests pass the 'no clip yet' check; the unique constraint makes one lose,
    and the loser answers with the winner's clip instead of a 500."""
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    real_lookup = api._existing_clip
    calls = {"n": 0}

    def racy_lookup(db, candidate):
        calls["n"] += 1
        if calls["n"] == 1:  # first check: pretend nobody else has started
            winner = Clip(
                candidate_id=candidate.id,
                video_id=candidate.video_id,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                duration_seconds=candidate.duration_seconds,
                celery_task_id="winner",
            )
            db.add(winner)
            db.commit()  # the other request's transaction lands (and commits) first
            return None
        return real_lookup(db, candidate)

    monkeypatch.setattr(api, "_existing_clip", racy_lookup)
    response = client.post(clip_url(ctx))
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    rows = db_session.scalars(__import__("sqlalchemy").select(Clip)).all()
    assert len(rows) == 1


def test_generate_when_queue_is_down_leaves_no_row(client, db_session, settings, monkeypatch):
    sign_up(client)
    ctx = candidate_setup(client, db_session)

    def down(clip_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_clip_render", down)
    assert client.post(clip_url(ctx)).status_code == 503
    assert client.get(clip_url(ctx)).status_code == 404


# --- status -----


def test_get_clip_404_before_generation_then_reports_state(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    assert client.get(clip_url(ctx)).status_code == 404
    optional = client.get(clip_url(ctx), params={"optional": "true"})
    assert optional.status_code == 200 and optional.json() is None
    clip_id = client.post(clip_url(ctx)).json()["id"]
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    clip.status, clip.progress_percent = "rendering", 10
    clip.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.clip_render_stale_after_seconds + 5
    )
    db_session.commit()

    data = client.get(clip_url(ctx)).json()
    assert (
        data["status"] == "rendering"
        and data["progress_percent"] == 10
        and data["is_stale"] is True
    )


def test_failed_clip_exposes_safe_error_only(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    clip.status, clip.error_code, clip.error_message = (
        "failed",
        "ffmpeg_failed",
        "Rendering failed (ffmpeg exit code 1)",
    )
    db_session.commit()
    data = client.get(clip_url(ctx)).json()
    assert data["error_code"] == "ffmpeg_failed" and "exit code 1" in data["error_message"]
    assert "/" not in data["error_message"]


# --- retry -----


def test_retry_resets_a_failed_clip_with_a_new_token(client, db_session, settings, fake_queues):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    old_token = clip.celery_task_id
    clip.status, clip.error_code, clip.error_message, clip.progress_percent = (
        "failed",
        "ffmpeg_failed",
        "x",
        10,
    )
    db_session.commit()

    response = client.post(f"{clip_url(ctx)}/retry")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued" and data["progress_percent"] == 0 and data["attempt"] == 2
    assert data["error_code"] is None and data["error_message"] is None
    assert data["id"] == clip_id  # same clip identity
    db_session.refresh(clip)
    assert clip.celery_task_id != old_token and fake_queues[-1] == (clip.id, clip.celery_task_id)


def test_retry_allows_a_stale_render(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    clip.status = "rendering"
    clip.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.clip_render_stale_after_seconds + 5
    )
    db_session.commit()
    assert client.post(f"{clip_url(ctx)}/retry").status_code == 200


def test_retry_refuses_live_ready_or_exhausted_clips(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    assert client.post(f"{clip_url(ctx)}/retry").status_code == 409  # queued
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    mark_ready(db_session, clip)
    assert client.post(f"{clip_url(ctx)}/retry").status_code == 409
    clip.status, clip.attempt = "failed", settings.clip_render_max_attempts
    db_session.commit()
    response = client.post(f"{clip_url(ctx)}/retry")
    assert response.status_code == 409 and "too many times" in response.json()["detail"]


def test_retry_when_queue_is_down_marks_failed(client, db_session, settings, monkeypatch):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    db_session.get(Clip, uuid.UUID(clip_id)).status = "failed"
    db_session.commit()

    def down(clip_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_clip_render", down)
    assert client.post(f"{clip_url(ctx)}/retry").status_code == 503
    data = client.get(clip_url(ctx)).json()
    assert data["status"] == "failed" and data["error_code"] == "queue_unavailable"


# --- listing -----


def test_list_clips_for_a_video_newest_first(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session, candidates=3)
    ids = []
    for index in range(3):
        clip_id = client.post(clip_url(ctx, index)).json()["id"]
        clip = db_session.get(Clip, uuid.UUID(clip_id))
        clip.created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
        db_session.commit()
        ids.append(clip_id)

    page = client.get(clips_url(ctx), params={"limit": 2}).json()
    assert page["total"] == 3 and [c["id"] for c in page["clips"]] == [ids[2], ids[1]]
    assert page["clips"][0]["title"] == "Moment 3"
    page = client.get(clips_url(ctx), params={"limit": 2, "offset": 2}).json()
    assert [c["id"] for c in page["clips"]] == [ids[0]]
    assert client.get(clips_url(ctx), params={"limit": 0}).status_code == 422
    assert client.get(clips_url(ctx), params={"limit": 101}).status_code == 422


# --- hardening -----


def test_ready_clip_with_missing_file_becomes_retryable(client, db_session, settings, fake_queues):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    clip.status, clip.storage_key, clip.file_size = "ready", f"clips/{clip.id}/clip.mp4", 10
    db_session.commit()  # no file was ever written at that key

    data = client.get(clip_url(ctx)).json()
    assert data["status"] == "failed" and data["error_code"] == "artifact_missing"
    assert "retry" in data["error_message"]
    listed = client.get(clips_url(ctx)).json()["clips"][0]
    assert listed["status"] == "failed"

    retried = client.post(f"{clip_url(ctx)}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "queued"


def test_generate_on_a_ready_clip_with_missing_file_asks_for_retry(client, db_session, settings):
    sign_up(client)
    ctx = candidate_setup(client, db_session)
    clip_id = client.post(clip_url(ctx)).json()["id"]
    clip = db_session.get(Clip, uuid.UUID(clip_id))
    clip.status, clip.storage_key = "ready", "../../etc/passwd"  # corrupted key: treated as missing
    db_session.commit()
    response = client.post(clip_url(ctx))
    assert response.status_code == 409 and "retry" in response.json()["detail"]
