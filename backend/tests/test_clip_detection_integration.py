"""Integration tests that tie the layers together without any real model or network:

- API → eager Celery task → pipeline → candidates read back through the API
- the real Ollama provider talking over real sockets to a tiny fake Ollama HTTP server
"""

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import clip_detection as api
from app.core.config import Settings, get_settings
from app.models import ClipDetectionRun, TranscriptSegment, Video
from app.services.clip_detection import pipeline
from app.services.clip_detection.contract import (
    AnalysisWindow,
    ClipAnalysisRequest,
    ClipProviderOutputError,
    TranscriptLine,
)
from app.services.clip_detection.ollama_provider import OllamaClipProvider
from app.workers.clip_detection_tasks import detect_clips
from tests.fakes import FakeClipProvider, raw_candidate

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024


# --- API → eager task → pipeline → API -----------------------------------------------------


class _Reusable:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wired(monkeypatch, db_session: Session):
    """Real enqueue (eager Celery), worker session = test session, fake provider."""
    monkeypatch.setattr(
        "app.workers.clip_detection_tasks.SessionLocal", lambda: _Reusable(db_session)
    )
    monkeypatch.setattr(
        pipeline,
        "_default_provider_factory",
        lambda name, model, s: FakeClipProvider(
            respond=lambda r: (
                raw_candidate(r.window.start, r.window.start + 30.0, hook_score=95),
                raw_candidate(r.window.start + 60.0, r.window.start + 90.0, hook_score=70),
                raw_candidate(r.window.start, r.window.start + 2.0),  # too short → rejected
            )
        ),
    )
    settings = Settings(**{**get_settings().model_dump(), "openai_api_key": None})
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)


def _transcribed_video(client: TestClient, db_session: Session) -> tuple[str, str]:
    assert (
        client.post(
            "/auth/register", json={"email": "e2e@example.com", "password": PASSWORD}
        ).status_code
        == 201
    )
    project_id = client.post("/projects", json={"name": "Stream"}).json()["id"]
    video_id = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", MP4_BYTES, "video/mp4")}
    ).json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    video.status, video.error_message, video.duration_seconds = "ready", None, 600.0
    db_session.commit()
    assert client.post(f"/projects/{project_id}/videos/{video_id}/transcription").status_code == 200
    transcription = video.transcription
    transcription.status, transcription.progress_percent, transcription.language = (
        "completed",
        100,
        "en",
    )
    for i in range(120):
        transcription.segments.append(
            TranscriptSegment(
                sequence_index=i, start_time=i * 5.0, end_time=(i + 1) * 5.0, text=f"line {i}"
            )
        )
    db_session.commit()
    return project_id, video_id


def test_start_runs_the_job_inline_and_candidates_come_back_through_the_api(
    wired, client: TestClient, db_session: Session
):
    project_id, video_id = _transcribed_video(client, db_session)
    url = f"/projects/{project_id}/videos/{video_id}/clip-detection"

    started = client.post(url, json={"provider": "ollama"})
    assert started.status_code == 201
    run_id = started.json()["id"]

    # Eager Celery executed the task during the POST; the DB row is already completed.
    status = client.get(f"{url}/{run_id}").json()
    assert status["status"] == "completed" and status["progress_percent"] == 100
    assert status["windows_total"] == status["windows_done"] >= 2
    assert status["candidate_count"] >= 2
    assert status["transcript_current"] is True

    page = client.get(f"{url}/{run_id}/candidates").json()
    assert page["total"] == status["candidate_count"]
    ranks = [c["rank"] for c in page["candidates"]]
    assert ranks == list(range(1, len(ranks) + 1))
    scores = [c["overall_score"] for c in page["candidates"]]
    assert scores == sorted(scores, reverse=True)
    for candidate in page["candidates"]:
        assert 0 <= candidate["start"] < candidate["end"] <= 600.0
        assert candidate["start"] % 5 == 0 and candidate["end"] % 5 == 0  # line boundaries
        assert candidate["transcript_excerpt"].startswith("line")
        assert candidate["duration"] >= 15

    run = db_session.get(ClipDetectionRun, uuid.UUID(run_id))
    assert run.celery_task_id and uuid.UUID(run.celery_task_id)  # pre-chosen, committed


def test_a_second_run_after_completion_is_independent_history(wired, client, db_session):
    project_id, video_id = _transcribed_video(client, db_session)
    url = f"/projects/{project_id}/videos/{video_id}/clip-detection"
    first = client.post(url, json={"provider": "ollama"}).json()["id"]
    second = client.post(url, json={"provider": "ollama"}).json()["id"]
    assert first != second
    page = client.get(url).json()
    assert page["total"] == 2 and {r["status"] for r in page["runs"]} == {"completed"}
    assert client.get(f"{url}/{first}/candidates").json()["total"] >= 1
    assert client.get(f"{url}/{second}/candidates").json()["total"] >= 1


def test_task_received_from_the_broker_shape_is_an_id_string(wired, client, db_session):
    """What the worker gets is exactly a string id (JSON-serialisable, nothing else)."""
    project_id, video_id = _transcribed_video(client, db_session)
    url = f"/projects/{project_id}/videos/{video_id}/clip-detection"
    run_id = client.post(url, json={"provider": "ollama"}).json()["id"]
    detect_clips.apply(args=[run_id])  # duplicate delivery of the same id → quiet no-op
    assert client.get(f"{url}/{run_id}").json()["status"] == "completed"


# --- real provider over real sockets against a fake Ollama ---------------------------------


class FakeOllama(BaseHTTPRequestHandler):
    """Speaks just enough of the Ollama HTTP API for the provider."""

    received: list[dict] = []
    mode = "ok"

    def log_message(self, *args):  # keep test output clean
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": "llama3.2:3b"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        FakeOllama.received.append(body)
        if self.path != "/api/chat":
            return self._json(404, {"error": "not found"})
        if FakeOllama.mode == "missing-model":
            return self._json(404, {"error": f"model '{body['model']}' not found"})
        if FakeOllama.mode == "garbage":
            content = "I am not JSON"
        else:
            window_text = body["messages"][1]["content"]
            start = (
                float(window_text.split("[", 1)[1].split(" ", 1)[0]) if "[" in window_text else 0.0
            )
            content = json.dumps(
                {
                    "candidates": [
                        {
                            "start_seconds": start,
                            "end_seconds": start + 30,
                            "title": "Opening",
                            "hook": "Strong start",
                            "rationale": "Self-contained",
                            "category": "story",
                            "hook_score": 80,
                            "entertainment_score": 70,
                            "clarity_score": 75,
                            "payoff_score": 65,
                            "completeness_score": 70,
                        }
                    ]
                }
            )
        self._json(
            200,
            {
                "model": body["model"],
                "message": {"role": "assistant", "content": content},
                "done": True,
                "done_reason": "stop",
            },
        )

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_ollama():
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    FakeOllama.received.clear()
    FakeOllama.mode = "ok"
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _settings_for(base_url: str) -> Settings:
    return Settings(
        **{
            **get_settings().model_dump(),
            "ollama_base_url": base_url,
            "ollama_connect_timeout_seconds": 2,
            "ollama_timeout_seconds": 10,
        }
    )


def _request() -> ClipAnalysisRequest:
    lines = tuple(TranscriptLine(600.0 + 5 * i, 605.0 + 5 * i, f"line {i}") for i in range(8))
    return ClipAnalysisRequest(
        window=AnalysisWindow(index=0, start=600.0, end=640.0, lines=lines),
        video_duration=3600.0,
        min_clip_seconds=15,
        max_clip_seconds=90,
        max_candidates=3,
        language="en",
    )


def test_real_provider_round_trips_over_http(fake_ollama):
    provider = OllamaClipProvider(_settings_for(fake_ollama), "llama3.2:3b")
    assert provider.check_availability().available is True

    result = provider.analyze(_request())

    (candidate,) = result.candidates
    assert candidate.start == 600.0 and candidate.end == 630.0 and candidate.title == "Opening"
    (body,) = FakeOllama.received
    assert body["model"] == "llama3.2:3b" and body["stream"] is False
    assert body["format"]["additionalProperties"] is False
    assert "[600.0 → 605.0] line 0" in body["messages"][1]["content"]


def test_real_provider_maps_server_side_errors(fake_ollama):
    provider = OllamaClipProvider(_settings_for(fake_ollama), "llama3.2:3b")
    FakeOllama.mode = "garbage"
    with pytest.raises(ClipProviderOutputError):
        provider.analyze(_request())
    FakeOllama.mode = "missing-model"
    with pytest.raises(Exception) as info:
        provider.analyze(_request())
    assert getattr(info.value, "code", None) == "model_not_installed"


def test_unreachable_endpoint_is_reported_quickly():
    provider = OllamaClipProvider(_settings_for("http://127.0.0.1:9"), "llama3.2:3b")
    diagnostics = provider.check_availability()
    assert diagnostics.available is False
    assert diagnostics.detail == "The local inference server is not reachable"
