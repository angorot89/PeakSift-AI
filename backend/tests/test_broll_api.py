"""The B-roll API: idempotent start, deliberate regeneration, polling, retry with fresh attempt
tokens, the creator's decision per suggestion, honest method labels, nothing internal in
responses, and ownership (401 anonymous, 404 for anyone else)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.api import broll as api
from app.core.config import get_settings
from app.models import BrollAnalysis, BrollSuggestion
from app.workers.dispatch import JobQueueUnavailable
from tests.test_clip_edit_api import ready_clip, sign_up


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch, db_session):
    """No real jobs; prove the attempt token is committed before enqueue."""
    queued: list[tuple[uuid.UUID, str]] = []

    def fake_enqueue(analysis_id, *, task_id):
        row = db_session.get(BrollAnalysis, analysis_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append((analysis_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_broll_analysis", fake_enqueue)
    return queued


def clip_ctx(db, email="owner@example.com", **kwargs) -> dict:
    ctx = ready_clip(db, email, **kwargs)
    ctx["base"] = ctx["base"].removesuffix("/edits") + "/broll"
    return ctx


def complete(db, analysis_id: str, *, provider="ollama", fallback=None) -> BrollAnalysis:
    analysis = db.get(BrollAnalysis, uuid.UUID(analysis_id))
    analysis.status, analysis.progress_percent = "completed", 100
    analysis.provider, analysis.fallback_reason = provider, fallback
    analysis.suggestion_count, analysis.rejected_count = 2, 1
    for index, (start, end, query) in enumerate(
        [(4.0, 7.0, "Moon / spacecraft"), (1.0, 3.0, "rocket")]
    ):
        db.add(
            BrollSuggestion(
                analysis=analysis, clip_id=analysis.clip_id, sequence_index=1 - index,
                start_time=start, end_time=end, query=query, reason="Supports the line",
                score=80, provider=provider, provider_version="m",
            )
        )  # fmt: skip
    db.commit()
    return analysis


def test_start_is_idempotent_and_commits_the_token_before_enqueueing(
    client, db_session, fake_queue
):
    sign_up(client)
    ctx = clip_ctx(db_session)
    first = client.post(f"{ctx['base']}/analyses")
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "queued" and body["generation"] == 1 and body["method"] == "local_ai"
    assert not {"celery_task_id", "config", "config_fingerprint", "provider", "model"} & set(body)
    again = client.post(f"{ctx['base']}/analyses", json={})
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    assert len(fake_queue) == 1
    assert client.get(ctx["base"]).json() == {"analysis": again.json(), "suggestions": []}


def test_state_and_suggestions_once_completed_in_time_order(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    analysis_id = client.post(f"{ctx['base']}/analyses").json()["id"]
    assert client.get(f"{ctx['base']}/analyses/{analysis_id}/suggestions").status_code == 409
    complete(db_session, analysis_id)
    state = client.get(ctx["base"]).json()
    assert state["analysis"]["status"] == "completed"
    assert [(s["start"], s["end"], s["query"], s["status"]) for s in state["suggestions"]] == [
        (1.0, 3.0, "rocket", "suggested"),
        (4.0, 7.0, "Moon / spacecraft", "suggested"),
    ]
    assert "score" not in state["suggestions"][0] and "provider" not in state["suggestions"][0]
    listed = client.get(f"{ctx['base']}/analyses/{analysis_id}/suggestions").json()
    assert listed == state["suggestions"]


@pytest.mark.parametrize(
    ("provider", "fallback", "label"),
    [("ollama", None, "local_ai"), ("keyword", "provider_unavailable", "keyword_fallback"),
     ("keyword", None, "keyword")],
)  # fmt: skip
def test_the_method_is_labelled_honestly(client, db_session, provider, fallback, label):
    sign_up(client)
    ctx = clip_ctx(db_session)
    analysis_id = client.post(f"{ctx['base']}/analyses").json()["id"]
    complete(db_session, analysis_id, provider=provider, fallback=fallback)
    assert client.get(f"{ctx['base']}/analyses/{analysis_id}").json()["method"] == label


def test_regeneration_is_deliberate_and_only_after_the_current_run(client, db_session, fake_queue):
    sign_up(client)
    ctx = clip_ctx(db_session)
    first = client.post(f"{ctx['base']}/analyses").json()["id"]
    running = client.post(f"{ctx['base']}/analyses", json={"regenerate": True})
    assert running.status_code == 409
    complete(db_session, first)
    second = client.post(f"{ctx['base']}/analyses", json={"regenerate": True})
    assert second.status_code == 201 and second.json()["generation"] == 2
    assert second.json()["id"] != first and len(fake_queue) == 2
    assert client.get(ctx["base"]).json()["analysis"]["id"] == second.json()["id"]
    assert client.post(f"{ctx['base']}/analyses", json={"regenerate": "yes"}).status_code == 422
    assert client.post(f"{ctx['base']}/analyses", json={"provider": "openai"}).status_code == 422


def test_a_failed_run_is_retried_on_the_same_row_with_a_fresh_token(client, db_session, fake_queue):
    sign_up(client)
    ctx = clip_ctx(db_session)
    analysis_id = client.post(f"{ctx['base']}/analyses").json()["id"]
    row = db_session.get(BrollAnalysis, uuid.UUID(analysis_id))
    assert client.post(f"{ctx['base']}/analyses/{analysis_id}/retry").status_code == 409  # queued
    row.status, row.error_code, row.error_message = "failed", "provider_timeout", "Too slow"
    db_session.commit()
    assert client.post(f"{ctx['base']}/analyses").status_code == 409  # use retry
    old_token = row.celery_task_id
    retried = client.post(f"{ctx['base']}/analyses/{analysis_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["attempt"] == 2 and retried.json()["status"] == "queued"
    assert retried.json()["error_code"] is None
    db_session.refresh(row)
    assert row.celery_task_id != old_token and fake_queue[-1] == (row.id, row.celery_task_id)


def test_a_stalled_run_can_be_retried_and_attempts_are_bounded(client, db_session, monkeypatch):
    sign_up(client)
    ctx = clip_ctx(db_session)
    analysis_id = client.post(f"{ctx['base']}/analyses").json()["id"]
    row = db_session.get(BrollAnalysis, uuid.UUID(analysis_id))
    row.status = "analyzing"
    row.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=get_settings().broll_stale_after_seconds + 5
    )
    db_session.commit()
    assert client.get(f"{ctx['base']}/analyses/{analysis_id}").json()["is_stale"] is True
    assert client.post(f"{ctx['base']}/analyses/{analysis_id}/retry").status_code == 200
    monkeypatch.setattr(get_settings(), "broll_max_attempts", 2)
    row.status = "failed"
    db_session.commit()
    response = client.post(f"{ctx['base']}/analyses/{analysis_id}/retry")
    assert response.status_code == 409 and "too many" in response.json()["detail"]


def test_suggestions_record_the_creators_decision(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    analysis_id = client.post(f"{ctx['base']}/analyses").json()["id"]
    complete(db_session, analysis_id)
    suggestion = client.get(ctx["base"]).json()["suggestions"][0]["id"]
    url = f"{ctx['base']}/suggestions/{suggestion}"
    for decision in ("dismissed", "suggested", "accepted"):
        response = client.patch(url, json={"status": decision})
        assert response.status_code == 200 and response.json()["status"] == decision
    assert client.patch(url, json={"status": "used"}).status_code == 422
    assert client.patch(url, json={"status": "accepted", "asset_id": "x"}).status_code == 422


@pytest.mark.parametrize(("kwargs", "detail"), [
    ({"clip_status": "rendering"}, "Generate the clip"),
    ({"transcript": False}, "completed transcript"),
])  # fmt: skip
def test_start_needs_a_ready_clip_and_a_transcript(client, db_session, kwargs, detail):
    sign_up(client)
    ctx = clip_ctx(db_session, **kwargs)
    response = client.post(f"{ctx['base']}/analyses")
    assert response.status_code == 409 and detail in response.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(BrollAnalysis)) == 0


def test_an_unavailable_queue_leaves_no_orphan_row(client, db_session, monkeypatch):
    sign_up(client)
    ctx = clip_ctx(db_session)

    def down(analysis_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_broll_analysis", down)
    assert client.post(f"{ctx['base']}/analyses").status_code == 503
    assert db_session.scalar(select(func.count()).select_from(BrollAnalysis)) == 0


def routes(ctx, analysis_id, suggestion_id):
    base = ctx["base"]
    return [
        ("get", base, None),
        ("post", f"{base}/analyses", None),
        ("get", f"{base}/analyses/{analysis_id}", None),
        ("get", f"{base}/analyses/{analysis_id}/suggestions", None),
        ("post", f"{base}/analyses/{analysis_id}/retry", None),
        ("patch", f"{base}/suggestions/{suggestion_id}", {"status": "dismissed"}),
    ]


def test_ownership_anonymous_401_and_others_404(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    analysis_id = client.post(f"{ctx['base']}/analyses").json()["id"]
    complete(db_session, analysis_id)
    suggestion_id = client.get(ctx["base"]).json()["suggestions"][0]["id"]
    client.post("/auth/logout")
    for method, url, body in routes(ctx, analysis_id, suggestion_id):
        kwargs = {"json": body} if body else {}
        assert getattr(client, method)(url, **kwargs).status_code == 401, url
    sign_up(client, "intruder@example.com")
    for method, url, body in routes(ctx, analysis_id, suggestion_id):
        kwargs = {"json": body} if body else {}
        assert getattr(client, method)(url, **kwargs).status_code == 404, url
    assert db_session.get(BrollSuggestion, uuid.UUID(suggestion_id)).status == "suggested"


def test_another_clips_analysis_or_suggestion_is_404_here(client, db_session):
    sign_up(client)
    first, second = clip_ctx(db_session), clip_ctx(db_session)
    analysis_id = client.post(f"{first['base']}/analyses").json()["id"]
    complete(db_session, analysis_id)
    suggestion_id = client.get(first["base"]).json()["suggestions"][0]["id"]
    assert client.get(f"{second['base']}/analyses/{analysis_id}").status_code == 404
    response = client.patch(
        f"{second['base']}/suggestions/{suggestion_id}", json={"status": "dismissed"}
    )
    assert response.status_code == 404
