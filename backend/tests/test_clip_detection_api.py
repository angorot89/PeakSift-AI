import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import clip_detection as api
from app.core.config import Settings, get_settings
from app.models import ClipCandidate, ClipDetectionRun, TranscriptSegment, Video
from app.services.clip_detection.contract import ProviderDiagnostics
from app.workers.dispatch import JobQueueUnavailable

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024

RUN_KEYS = {
    "id",
    "video_id",
    "transcription_id",
    "provider",
    "model",
    "status",
    "progress_percent",
    "windows_total",
    "windows_done",
    "attempt",
    "candidate_count",
    "is_stale",
    "transcript_current",
    "config",
    "error_code",
    "error_message",
    "created_at",
    "started_at",
    "completed_at",
}


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch, db_session):
    """Never run the real pipeline; record (run_id, task_id) and prove the token was committed."""
    queued: list[tuple[uuid.UUID, str]] = []

    def fake_enqueue(run_id, *, task_id):
        row = db_session.get(ClipDetectionRun, run_id)
        assert row is not None and row.celery_task_id == task_id  # committed before enqueue
        queued.append((run_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_clip_detection", fake_enqueue)
    return queued


@pytest.fixture
def settings(monkeypatch) -> Settings:
    base = get_settings().model_dump()
    base["openai_api_key"] = None
    settings = Settings(**base)
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    return settings


def sign_up(client: TestClient, email: str = "owner@example.com") -> None:
    assert (
        client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )


def transcribed_video(
    client: TestClient, db_session: Session, *, lines: int = 60
) -> tuple[str, str]:
    """A ready video with a completed 5-minute transcript (60 lines of 5 s)."""
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    response = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", MP4_BYTES, "video/mp4")}
    )
    video_id = response.json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    video.status, video.error_message, video.duration_seconds = "ready", None, lines * 5.0
    db_session.commit()
    assert client.post(f"/projects/{project_id}/videos/{video_id}/transcription").status_code == 200
    transcription = video.transcription
    transcription.status, transcription.progress_percent, transcription.language = (
        "completed",
        100,
        "en",
    )
    for i in range(lines):
        transcription.segments.append(
            TranscriptSegment(
                sequence_index=i, start_time=i * 5.0, end_time=(i + 1) * 5.0, text=f"line {i}"
            )
        )
    db_session.commit()
    return project_id, video_id


def base(project_id: str, video_id: str) -> str:
    return f"/projects/{project_id}/videos/{video_id}/clip-detection"


def start(client: TestClient, project_id: str, video_id: str, **body):
    payload = {"provider": "ollama", **body}
    return client.post(base(project_id, video_id), json=payload)


def complete_run(db_session: Session, run_id: str, candidates: int = 3) -> ClipDetectionRun:
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    run.status, run.progress_percent, run.windows_total, run.windows_done = "completed", 100, 2, 2
    run.completed_at = datetime.now(UTC)
    for rank in range(1, candidates + 1):
        start_time = rank * 30.0
        run.candidates.append(
            ClipCandidate(
                video_id=run.video_id,
                start_time=start_time,
                end_time=start_time + 20.0,
                duration_seconds=20.0,
                title=f"Moment {rank}",
                hook=f"Hook {rank}",
                rationale="Because.",
                category="story",
                transcript_excerpt=f"line {rank}",
                overall_score=100 - rank,
                hook_score=90,
                entertainment_score=80,
                clarity_score=70,
                payoff_score=60,
                completeness_score=50,
                rank=rank,
            )
        )
    db_session.commit()
    return run


# --- authentication and ownership -----


def test_all_endpoints_require_authentication(client: TestClient):
    url = base(str(uuid.uuid4()), str(uuid.uuid4()))
    run, cand = uuid.uuid4(), uuid.uuid4()
    assert client.get("/clip-detection/providers").status_code == 401
    assert client.post(url, json={"provider": "ollama"}).status_code == 401
    assert client.get(url).status_code == 401
    assert client.get(f"{url}/{run}").status_code == 401
    assert client.post(f"{url}/{run}/retry").status_code == 401
    assert client.get(f"{url}/{run}/candidates").status_code == 401
    assert client.get(f"{url}/{run}/candidates/{cand}").status_code == 401
    for action in ("save", "dismiss", "reset"):
        assert client.post(f"{url}/{run}/candidates/{cand}/{action}").status_code == 401


def test_other_user_cannot_reach_runs_or_candidates(
    client: TestClient, db_session: Session, settings
):
    sign_up(client, "alice@example.com")
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    complete_run(db_session, run_id)
    candidate_id = str(db_session.get(ClipDetectionRun, uuid.UUID(run_id)).candidates[0].id)
    client.cookies.clear()
    sign_up(client, "bob@example.com")

    url = base(project_id, video_id)
    assert start(client, project_id, video_id).status_code == 404
    assert client.get(url).status_code == 404
    assert client.get(f"{url}/{run_id}").status_code == 404
    assert client.post(f"{url}/{run_id}/retry").status_code == 404
    assert client.get(f"{url}/{run_id}/candidates").status_code == 404
    assert client.get(f"{url}/{run_id}/candidates/{candidate_id}").status_code == 404
    assert client.post(f"{url}/{run_id}/candidates/{candidate_id}/save").status_code == 404


def test_run_from_another_video_is_not_found(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    other_project, other_video = transcribed_video(client, db_session)
    assert client.get(f"{base(other_project, other_video)}/{run_id}").status_code == 404


# --- providers -----


def test_providers_list_reflects_configuration_without_secrets(client, settings, monkeypatch):
    sign_up(client)
    monkeypatch.setattr(settings, "ollama_base_url", "http://inference.internal:11434")
    response = client.get("/clip-detection/providers")
    assert response.status_code == 200
    options = {o["name"]: o for o in response.json()}
    assert options["ollama"]["configured"] is True
    assert options["ollama"]["models"] == ["llama3.2:3b"]
    assert options["ollama"]["available"] is None  # not probed without ?diagnose
    assert options["openai"]["configured"] is False
    assert options["openai"]["detail"] == "OpenAI is not configured on this server"
    assert "inference.internal" not in response.text and "sk-" not in response.text


def test_providers_diagnose_probes_configured_providers_only(client, settings, monkeypatch):
    sign_up(client)
    probed: list[tuple[str, str]] = []

    class Probe:
        def __init__(self, name, model):
            self.name, self.model = name, model

        def check_availability(self):
            probed.append((self.name, self.model))
            return ProviderDiagnostics(available=False, detail="Model 'x' is not installed")

    monkeypatch.setattr(api, "get_clip_provider", lambda name, model, s: Probe(name, model))
    response = client.get("/clip-detection/providers?diagnose=true")
    options = {o["name"]: o for o in response.json()}
    assert probed == [("ollama", "llama3.2:3b")]  # openai is unconfigured → not probed
    assert options["ollama"]["available"] is False
    assert options["ollama"]["detail"] == "Model 'x' is not installed"


def test_providers_diagnose_with_openai_key(client, settings, monkeypatch):
    sign_up(client)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test"))
    monkeypatch.setattr(
        api,
        "get_clip_provider",
        lambda name, model, s: type(
            "P", (), {"check_availability": lambda self: ProviderDiagnostics(True, "ready")}
        )(),
    )
    options = {o["name"]: o for o in client.get("/clip-detection/providers?diagnose=true").json()}
    assert options["openai"]["configured"] is True and options["openai"]["available"] is True
    assert options["openai"]["models"] == ["gpt-5-mini", "gpt-5"]
    assert "sk-test" not in str(options)


# --- start -----


def test_start_creates_a_queued_run_with_snapshot_and_token(
    client, db_session, settings, fake_queue
):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)

    response = start(client, project_id, video_id)

    assert response.status_code == 201
    data = response.json()
    assert set(data) == RUN_KEYS
    assert data["status"] == "queued" and data["progress_percent"] == 0
    assert data["provider"] == "ollama" and data["model"] == "llama3.2:3b"
    assert data["attempt"] == 1 and data["candidate_count"] == 0
    assert data["transcript_current"] is True and data["is_stale"] is False
    assert data["config"]["window_seconds"] == settings.clip_detection_window_seconds
    assert "celery_task_id" not in data and "transcript_fingerprint" not in data
    run = db_session.get(ClipDetectionRun, uuid.UUID(data["id"]))
    assert len(run.transcript_fingerprint) == 64
    assert fake_queue == [(run.id, run.celery_task_id)]


def test_start_accepts_an_allowed_model_and_refuses_others(
    client, db_session, settings, monkeypatch
):
    sign_up(client)
    monkeypatch.setattr(settings, "ollama_clip_models", "llama3.2:3b,qwen2.5:7b")
    project_id, video_id = transcribed_video(client, db_session)

    response = start(client, project_id, video_id, model="qwen2.5:7b")
    assert response.status_code == 201 and response.json()["model"] == "qwen2.5:7b"

    other_project, other_video = transcribed_video(client, db_session)
    response = start(client, other_project, other_video, model="llama3.2:1b")
    assert response.status_code == 400
    assert response.json()["detail"] == "Model is not allowed for provider 'ollama'"
    assert "llama3.2:1b" not in response.text


def test_start_refuses_unknown_or_unconfigured_provider(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    assert start(client, project_id, video_id, provider="anthropic").status_code == 400
    response = start(client, project_id, video_id, provider="openai")
    assert response.status_code == 400
    assert response.json()["detail"] == "OpenAI is not configured on this server"


def test_start_requires_a_completed_transcript(client, db_session, settings):
    sign_up(client)
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    video_id = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", MP4_BYTES, "video/mp4")}
    ).json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    video.status, video.duration_seconds = "ready", 300.0
    db_session.commit()

    response = start(client, project_id, video_id)  # no transcription at all
    assert response.status_code == 409
    assert response.json()["detail"] == "Transcribe the video before detecting clips"

    client.post(f"/projects/{project_id}/videos/{video_id}/transcription")
    assert start(client, project_id, video_id).status_code == 409  # queued, not completed


def test_start_refuses_a_video_that_is_not_ready(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    db_session.get(Video, uuid.UUID(video_id)).status = "failed"
    db_session.commit()
    assert start(client, project_id, video_id).status_code == 409


def test_start_refuses_an_empty_transcript(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    for segment in db_session.get(Video, uuid.UUID(video_id)).transcription.segments:
        segment.text = " "
    db_session.commit()
    response = start(client, project_id, video_id)
    assert response.status_code == 409
    assert "no spoken words" in response.json()["detail"]


def test_only_one_active_run_per_video(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    first = start(client, project_id, video_id)
    assert first.status_code == 201
    second = start(client, project_id, video_id)
    assert second.status_code == 409
    assert second.json()["detail"] == "A clip detection is already running for this video"

    complete_run(db_session, first.json()["id"])
    third = start(client, project_id, video_id)  # history accumulates once finished
    assert third.status_code == 201 and third.json()["id"] != first.json()["id"]


def test_start_when_queue_is_down_leaves_no_row(client, db_session, settings, monkeypatch):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)

    def down(run_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_clip_detection", down)
    response = start(client, project_id, video_id)
    assert response.status_code == 503
    assert client.get(base(project_id, video_id)).json()["total"] == 0


def test_start_validates_the_body(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    assert client.post(base(project_id, video_id), json={}).status_code == 422
    assert client.post(base(project_id, video_id), json={"provider": ""}).status_code == 422
    assert start(client, project_id, video_id, model="x" * 200).status_code == 422


# --- status and list -----


def test_get_run_reports_progress_candidates_and_staleness(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    run.status, run.progress_percent, run.windows_total, run.windows_done = "analyzing", 42, 4, 2
    run.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.clip_detection_stale_after_seconds + 5
    )
    db_session.commit()

    data = client.get(f"{base(project_id, video_id)}/{run_id}").json()
    assert data["status"] == "analyzing" and data["progress_percent"] == 42
    assert data["windows_total"] == 4 and data["windows_done"] == 2
    assert data["is_stale"] is True
    assert data["candidate_count"] == 0

    complete_run(db_session, run_id, candidates=3)
    data = client.get(f"{base(project_id, video_id)}/{run_id}").json()
    assert data["candidate_count"] == 3 and data["is_stale"] is False


def test_transcript_current_flag_turns_false_when_the_transcript_changes(
    client, db_session, settings
):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    complete_run(db_session, run_id)  # the flag is only evaluated once a run is no longer active
    video = db_session.get(Video, uuid.UUID(video_id))
    video.transcription.segments[0].text = "re-transcribed"
    db_session.commit()
    assert (
        client.get(f"{base(project_id, video_id)}/{run_id}").json()["transcript_current"] is False
    )


def test_list_runs_is_newest_first_and_paginated(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    ids = []
    for index in range(3):
        run_id = start(client, project_id, video_id).json()["id"]
        run = complete_run(db_session, run_id, candidates=1)
        # The suite runs inside one transaction, so the server-side now() default is the
        # same for every row; give each run its own creation time as real requests would.
        run.created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
        db_session.commit()
        ids.append(run_id)

    page = client.get(base(project_id, video_id), params={"limit": 2}).json()
    assert page["total"] == 3 and page["limit"] == 2 and page["offset"] == 0
    assert [r["id"] for r in page["runs"]] == [ids[2], ids[1]]
    page = client.get(base(project_id, video_id), params={"limit": 2, "offset": 2}).json()
    assert [r["id"] for r in page["runs"]] == [ids[0]]
    assert client.get(base(project_id, video_id), params={"limit": 0}).status_code == 422
    assert client.get(base(project_id, video_id), params={"limit": 101}).status_code == 422


def test_unknown_run_is_404(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    assert client.get(f"{base(project_id, video_id)}/{uuid.uuid4()}").status_code == 404


# --- retry -----


def test_retry_resets_a_failed_run_with_a_new_token(client, db_session, settings, fake_queue):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    old_token = run.celery_task_id
    run.status, run.error_code, run.error_message = "failed", "provider_unavailable", "down"
    run.progress_percent, run.windows_done = 30, 1
    db_session.commit()

    response = client.post(f"{base(project_id, video_id)}/{run_id}/retry")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued" and data["progress_percent"] == 0
    assert data["attempt"] == 2 and data["windows_done"] == 0
    assert data["error_code"] is None and data["error_message"] is None
    db_session.refresh(run)
    assert run.celery_task_id != old_token
    assert fake_queue[-1] == (run.id, run.celery_task_id)


def test_retry_allows_a_stale_run(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    run.status = "analyzing"
    run.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.clip_detection_stale_after_seconds + 5
    )
    db_session.commit()
    assert client.post(f"{base(project_id, video_id)}/{run_id}/retry").status_code == 200


def test_retry_refuses_live_or_completed_runs(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    assert client.post(f"{base(project_id, video_id)}/{run_id}/retry").status_code == 409  # queued
    complete_run(db_session, run_id)
    assert client.post(f"{base(project_id, video_id)}/{run_id}/retry").status_code == 409


def test_retry_refuses_when_the_transcript_changed(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    run.status = "failed"
    run.video.transcription.segments[3].text = "changed"
    db_session.commit()
    response = client.post(f"{base(project_id, video_id)}/{run_id}/retry")
    assert response.status_code == 409
    assert "transcript has changed" in response.json()["detail"]


def test_retry_when_queue_is_down_marks_the_run_failed(client, db_session, settings, monkeypatch):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    run.status = "failed"
    db_session.commit()

    def down(run_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_clip_detection", down)
    assert client.post(f"{base(project_id, video_id)}/{run_id}/retry").status_code == 503
    data = client.get(f"{base(project_id, video_id)}/{run_id}").json()
    assert data["status"] == "failed" and data["error_code"] == "queue_unavailable"


# --- candidates -----


def test_candidates_are_hidden_until_completed(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    response = client.get(f"{base(project_id, video_id)}/{run_id}/candidates")
    assert response.status_code == 409
    assert "queued" in response.json()["detail"]


def test_candidates_are_ranked_paginated_and_complete(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    complete_run(db_session, run_id, candidates=5)

    page = client.get(
        f"{base(project_id, video_id)}/{run_id}/candidates", params={"limit": 2}
    ).json()
    assert page["total"] == 5 and [c["rank"] for c in page["candidates"]] == [1, 2]
    first = page["candidates"][0]
    assert first["start"] == 30.0 and first["end"] == 50.0 and first["duration"] == 20.0
    assert first["title"] == "Moment 1" and first["hook"] == "Hook 1"
    assert first["scores"] == {
        "hook": 90,
        "entertainment": 80,
        "clarity": 70,
        "payoff": 60,
        "completeness": 50,
    }
    assert first["overall_score"] == 99 and first["category"] == "story"
    assert first["decision"] == "undecided" and first["decided_at"] is None
    assert first["transcript_excerpt"] == "line 1"

    page = client.get(
        f"{base(project_id, video_id)}/{run_id}/candidates", params={"limit": 2, "offset": 4}
    ).json()
    assert [c["rank"] for c in page["candidates"]] == [5]


def test_candidate_detail_and_decisions(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    complete_run(db_session, run_id, candidates=2)
    url = f"{base(project_id, video_id)}/{run_id}/candidates"
    first, second = (c["id"] for c in client.get(url).json()["candidates"])

    assert client.get(f"{url}/{first}").json()["rank"] == 1
    assert client.get(f"{url}/{uuid.uuid4()}").status_code == 404

    saved = client.post(f"{url}/{first}/save").json()
    assert saved["decision"] == "saved" and saved["decided_at"] is not None
    dismissed = client.post(f"{url}/{second}/dismiss").json()
    assert dismissed["decision"] == "dismissed"

    assert [c["decision"] for c in client.get(url).json()["candidates"]] == ["saved", "dismissed"]
    assert [
        c["id"] for c in client.get(url, params={"decision": "saved"}).json()["candidates"]
    ] == [first]
    assert client.get(url, params={"decision": "maybe"}).status_code == 422

    reset = client.post(f"{url}/{first}/reset").json()
    assert reset["decision"] == "undecided" and reset["decided_at"] is None
    db_session.expire_all()
    assert db_session.get(ClipCandidate, uuid.UUID(first)).decision == "undecided"


def test_candidate_of_another_run_is_not_found(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    first_run = start(client, project_id, video_id).json()["id"]
    complete_run(db_session, first_run, candidates=1)
    second_run = start(client, project_id, video_id).json()["id"]
    complete_run(db_session, second_run, candidates=1)
    candidate = client.get(f"{base(project_id, video_id)}/{first_run}/candidates").json()[
        "candidates"
    ][0]["id"]

    assert (
        client.get(f"{base(project_id, video_id)}/{second_run}/candidates/{candidate}").status_code
        == 404
    )
    assert (
        client.post(
            f"{base(project_id, video_id)}/{second_run}/candidates/{candidate}/save"
        ).status_code
        == 404
    )


# --- hardening -----


def test_transcript_current_is_not_evaluated_while_a_run_is_active(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]

    assert client.get(f"{base(project_id, video_id)}/{run_id}").json()["transcript_current"] is None
    complete_run(db_session, run_id)
    assert client.get(f"{base(project_id, video_id)}/{run_id}").json()["transcript_current"] is True


def test_retries_are_bounded_per_run(client, db_session, settings):
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    run.status, run.attempt = "failed", settings.clip_detection_max_attempts
    db_session.commit()

    response = client.post(f"{base(project_id, video_id)}/{run_id}/retry")
    assert response.status_code == 409
    assert "start a new detection" in response.json()["detail"]

    run.attempt = settings.clip_detection_max_attempts - 1
    db_session.commit()
    assert client.post(f"{base(project_id, video_id)}/{run_id}/retry").status_code == 200


def test_candidate_views_and_counts(client, db_session, settings):
    """ "Active" hides dismissed moments; "top" keeps rank 1 and strong editorial scores; every
    page reports how many moments each review filter holds."""
    sign_up(client)
    project_id, video_id = transcribed_video(client, db_session)
    run_id = start(client, project_id, video_id).json()["id"]
    complete_run(db_session, run_id, candidates=5)
    for candidate in db_session.scalars(
        select(ClipCandidate).where(ClipCandidate.run_id == uuid.UUID(run_id))
    ):
        candidate.overall_score = {1: 60, 2: 90, 3: 75, 4: 74, 5: 95}[candidate.rank]
    db_session.commit()
    url = f"{base(project_id, video_id)}/{run_id}/candidates"
    ids = [c["id"] for c in client.get(url).json()["candidates"]]
    client.post(f"{url}/{ids[4]}/dismiss")  # rank 5, the highest score
    client.post(f"{url}/{ids[3]}/save")

    def ranks(**params):
        return [c["rank"] for c in client.get(url, params=params).json()["candidates"]]

    assert ranks(view="active") == [1, 2, 3, 4]
    assert ranks(view="top") == [1, 2, 3]  # rank 1 always; 90 and 75 are strong; 74 is not
    assert ranks(view="top", limit=2, offset=1) == [2, 3]
    page = client.get(url, params={"view": "top"}).json()
    assert page["total"] == 3
    assert page["counts"] == {"active": 4, "top": 3, "saved": 1, "dismissed": 1}
    assert client.get(url, params={"view": "best"}).status_code == 422
