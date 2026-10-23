"""The authenticated smart-reframe API: ownership, idempotency, safe schemas, retry."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.api import reframe as api
from app.core.config import Settings, get_settings
from app.models import KeyframeMode, ReframeAnalysis, ReframeKeyframe, ReframeStatus
from app.services.reframe.detection import detector_available
from app.services.storage import LocalStorageProvider
from app.workers.dispatch import JobQueueUnavailable
from tests.test_clip_edit_api import ready_clip, sign_up

ANALYSIS_KEYS = {
    "id",
    "clip_id",
    "status",
    "progress_percent",
    "attempt",
    "is_stale",
    "provider",
    "algorithm_version",
    "sample_fps",
    "target_aspect_ratio",
    "source_width",
    "source_height",
    "overall_confidence",
    "confidence_level",
    "frames_sampled",
    "detections_count",
    "tracks_count",
    "subject_switches",
    "fallback_fraction",
    "error_code",
    "error_message",
    "created_at",
    "started_at",
    "completed_at",
}


@pytest.fixture
def storage() -> LocalStorageProvider:
    return LocalStorageProvider(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalStorageProvider):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch, db_session):
    """No real jobs; prove the attempt token is committed before enqueue."""
    queued: list[tuple[uuid.UUID, str]] = []

    def fake_enqueue(analysis_id, *, task_id):
        row = db_session.get(ReframeAnalysis, analysis_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append((analysis_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_reframe_analysis", fake_enqueue)
    monkeypatch.setattr(api, "detector_available", lambda settings: True)
    return queued


def clip_with_file(db: Session, storage: LocalStorageProvider, email="owner@example.com") -> dict:
    ctx = ready_clip(db, email)
    path = storage.path_for(ctx["clip"].storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"clip bytes")
    ctx["base"] = ctx["base"].replace("/edits", "/reframe")
    return ctx


def complete(db: Session, analysis_id: str, points=3) -> ReframeAnalysis:
    analysis = db.get(ReframeAnalysis, uuid.UUID(analysis_id))
    analysis.status, analysis.progress_percent = ReframeStatus.COMPLETED, 100
    analysis.source_width, analysis.source_height = 1920, 1080
    analysis.confidence_level, analysis.overall_confidence = "high", 0.8
    for i in reversed(range(points)):
        db.add(
            ReframeKeyframe(
                analysis=analysis,
                sequence_index=i,
                timestamp=i * 1.0,
                center_x=0.3 + 0.1 * i,
                center_y=0.5,
                crop_width=0.31640625,
                crop_height=1.0,
                confidence=0.9,
                mode=KeyframeMode.TRACKED,
            )
        )
    db.commit()
    return analysis


# --- authentication and ownership -----


def test_anonymous_requests_are_401(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    client.post("/auth/logout")
    for method, url in [
        ("post", ctx["base"]),
        ("get", ctx["base"]),
        ("get", f"{ctx['base']}/current"),
        ("get", f"{ctx['base']}/{analysis_id}"),
        ("get", f"{ctx['base']}/{analysis_id}/path"),
        ("post", f"{ctx['base']}/{analysis_id}/retry"),
    ]:
        assert getattr(client, method)(url).status_code == 401, url


def test_other_user_gets_404_everywhere(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    complete(db_session, analysis_id)
    client.post("/auth/logout")
    sign_up(client, "intruder@example.com")
    for method, url in [
        ("post", ctx["base"]),
        ("get", ctx["base"]),
        ("get", f"{ctx['base']}/current"),
        ("get", f"{ctx['base']}/{analysis_id}"),
        ("get", f"{ctx['base']}/{analysis_id}/path"),
        ("post", f"{ctx['base']}/{analysis_id}/retry"),
    ]:
        assert getattr(client, method)(url).status_code == 404, url
    assert db_session.scalar(select(func.count()).select_from(ReframeAnalysis)) == 1


def test_an_analysis_of_another_clip_is_404_under_this_clip(client, db_session, storage):
    sign_up(client)
    first, second = clip_with_file(db_session, storage), clip_with_file(db_session, storage)
    analysis_id = client.post(first["base"]).json()["id"]
    assert client.get(f"{second['base']}/{analysis_id}").status_code == 404


# --- start -----


def test_start_queues_an_analysis_with_a_safe_schema(client, db_session, storage, fake_queue):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    response = client.post(ctx["base"], json={"detector": "../evil", "model_path": "/etc/passwd"})
    assert response.status_code == 201
    data = response.json()
    assert set(data) == ANALYSIS_KEYS
    assert data["status"] == "queued" and data["attempt"] == 1 and data["provider"] == "yunet_face"
    assert data["algorithm_version"] == "smart_reframe_v1" and data["sample_fps"] == 2.0
    text = response.text
    for forbidden in (
        "celery",
        "task",
        "fingerprint",
        "model_path",
        "/etc",
        "evil",
        str(storage.root),
    ):
        assert forbidden not in text
    row = db_session.get(ReframeAnalysis, uuid.UUID(data["id"]))
    assert fake_queue == [(row.id, row.celery_task_id)]
    assert row.config["detector"] == "yunet_face"  # server configuration, not the request


def test_repeated_start_returns_the_same_analysis(client, db_session, storage, fake_queue):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    first = client.post(ctx["base"])
    second = client.post(ctx["base"])
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"] and len(fake_queue) == 1


def test_a_failed_analysis_must_be_retried_explicitly(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    db_session.get(ReframeAnalysis, uuid.UUID(analysis_id)).status = ReframeStatus.FAILED
    db_session.commit()
    response = client.post(ctx["base"])
    assert response.status_code == 409 and "retry" in response.json()["detail"]


def test_clip_must_be_ready_with_its_file(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    ctx["clip"].status = "rendering"
    db_session.commit()
    assert client.post(ctx["base"]).status_code == 409
    ctx["clip"].status = "ready"
    db_session.commit()
    storage.path_for(ctx["clip"].storage_key).unlink()
    response = client.post(ctx["base"])
    assert response.status_code == 409 and "missing" in response.json()["detail"]
    assert str(storage.root) not in response.text


def test_unavailable_detector_is_refused_up_front(client, db_session, storage, monkeypatch):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    monkeypatch.setattr(api, "detector_available", lambda settings: False)
    response = client.post(ctx["base"])
    assert (
        response.status_code == 409
        and response.json()["detail"] == "Smart framing is not available on this server"
    )
    assert db_session.scalar(select(func.count()).select_from(ReframeAnalysis)) == 0


def test_queue_down_on_start_leaves_no_row(client, db_session, storage, monkeypatch):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)

    def down(analysis_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_reframe_analysis", down)
    assert client.post(ctx["base"]).status_code == 503
    assert db_session.scalar(select(func.count()).select_from(ReframeAnalysis)) == 0


# --- read -----


def test_current_list_and_status(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    assert client.get(f"{ctx['base']}/current").status_code == 404
    # The app's check: "none yet" is a null answer, not a failed request.
    optional = client.get(f"{ctx['base']}/current", params={"optional": "true"})
    assert optional.status_code == 200 and optional.json() is None
    analysis_id = client.post(ctx["base"]).json()["id"]
    assert (
        client.get(f"{ctx['base']}/current", params={"optional": "true"}).json()["id"]
        == analysis_id
    )
    assert client.get(f"{ctx['base']}/current").json()["id"] == analysis_id
    assert client.get(f"{ctx['base']}/{analysis_id}").json()["status"] == "queued"
    page = client.get(ctx["base"]).json()
    assert page["total"] == 1 and [a["id"] for a in page["analyses"]] == [analysis_id]


def test_path_is_only_served_when_completed_and_in_order(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    assert client.get(f"{ctx['base']}/{analysis_id}/path").status_code == 409
    complete(db_session, analysis_id, points=4)
    data = client.get(f"{ctx['base']}/{analysis_id}/path").json()
    assert set(data) == {
        "analysis_id",
        "source_width",
        "source_height",
        "target_aspect_ratio",
        "keyframes",
    }
    assert (data["source_width"], data["source_height"], data["target_aspect_ratio"]) == (
        1920,
        1080,
        "9:16",
    )
    assert [k["timestamp"] for k in data["keyframes"]] == [0.0, 1.0, 2.0, 3.0]
    assert set(data["keyframes"][0]) == {
        "timestamp",
        "center_x",
        "center_y",
        "crop_width",
        "crop_height",
        "confidence",
        "mode",
    }


def test_unknown_ids_are_404(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    assert client.get(f"{ctx['base']}/{uuid.uuid4()}").status_code == 404
    assert client.get(f"{ctx['base']}/not-a-uuid").status_code == 422


# --- retry -----


def test_retry_only_failed_or_stalled_with_a_new_attempt(client, db_session, storage, fake_queue):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    assert client.post(f"{ctx['base']}/{analysis_id}/retry").status_code == 409  # queued
    complete(db_session, analysis_id)
    assert client.post(f"{ctx['base']}/{analysis_id}/retry").status_code == 409  # completed
    row = db_session.get(ReframeAnalysis, uuid.UUID(analysis_id))
    old_token = row.celery_task_id
    row.status, row.error_code, row.error_message = ReframeStatus.FAILED, "detector_failed", "x"
    db_session.commit()
    data = client.post(f"{ctx['base']}/{analysis_id}/retry").json()
    assert data["status"] == "queued" and data["attempt"] == 2 and data["error_code"] is None
    db_session.refresh(row)
    assert row.celery_task_id != old_token and fake_queue[-1] == (row.id, row.celery_task_id)
    assert db_session.scalar(select(func.count()).select_from(ReframeKeyframe)) == 0


def test_stalled_analysis_can_be_retried(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    row = db_session.get(ReframeAnalysis, uuid.UUID(analysis_id))
    row.status = ReframeStatus.DETECTING
    row.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=get_settings().reframe_stale_after_seconds + 5
    )
    db_session.commit()
    assert client.get(f"{ctx['base']}/{analysis_id}").json()["is_stale"] is True
    assert client.post(f"{ctx['base']}/{analysis_id}/retry").json()["attempt"] == 2


def test_retry_limit_and_row_lock(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    row = db_session.get(ReframeAnalysis, uuid.UUID(analysis_id))
    row.status = ReframeStatus.FAILED
    db_session.commit()
    statements = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        assert client.post(f"{ctx['base']}/{analysis_id}/retry").status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert any("FROM reframe_analyses" in s and "FOR UPDATE" in s for s in statements)
    row.status, row.attempt = ReframeStatus.FAILED, get_settings().reframe_max_attempts
    db_session.commit()
    response = client.post(f"{ctx['base']}/{analysis_id}/retry")
    assert response.status_code == 409 and "too many" in response.json()["detail"]


def test_retry_when_queue_is_down_marks_failed(client, db_session, storage, monkeypatch):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    analysis_id = client.post(ctx["base"]).json()["id"]
    db_session.get(ReframeAnalysis, uuid.UUID(analysis_id)).status = ReframeStatus.FAILED
    db_session.commit()

    def down(analysis_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_reframe_analysis", down)
    assert client.post(f"{ctx['base']}/{analysis_id}/retry").status_code == 503
    assert client.get(f"{ctx['base']}/{analysis_id}").json()["error_code"] == "queue_unavailable"


# --- detector readiness (real check, no model load) -----


def test_detector_readiness_requires_the_pinned_model(tmp_path: Path):
    base = get_settings().model_dump()
    assert (
        detector_available(Settings(**{**base, "reframe_model_path": str(tmp_path / "none.onnx")}))
        is False
    )
    fake = tmp_path / "fake.onnx"
    fake.write_bytes(b"not the model")
    assert detector_available(Settings(**{**base, "reframe_model_path": str(fake)})) is False
    assert detector_available(Settings(**{**base, "reframe_detector": "mediapipe_face"})) is False
