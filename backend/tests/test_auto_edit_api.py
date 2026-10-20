"""The Auto Edit API: recipes, idempotent plan creation per inputs, polling, retry with fresh
attempt tokens, regeneration that keeps history, applying a ready plan exactly once as a normal
edit (with every asset re-checked), nothing internal in responses, and ownership."""

import json
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.api import auto_edit as api
from app.api import clip_edits as edits_api
from app.core.config import get_settings
from app.models import AutoEditPlan, BrollAnalysis, BrollSuggestion, ClipEdit, VisualAsset
from app.services.auto_edit.contract import PlannerResult, parse_proposal
from app.services.auto_edit.pipeline import run_auto_edit_plan
from app.services.broll.config import BrollConfig
from app.services.storage import LocalStorageProvider, generate_key
from app.workers.dispatch import JobQueueUnavailable
from tests.test_auto_edit_contract import GOOD
from tests.test_clip_edit_api import ready_clip, sign_up

INTERNAL = {"celery_task_id", "source_fingerprint", "config", "planner_model", "planner_provider",
            "fallback_reason", "configuration_fingerprint"}  # fmt: skip


@pytest.fixture(autouse=True)
def fake_queues(monkeypatch, db_session):
    """No real jobs; prove each attempt token is committed before enqueueing."""
    queued = {"plans": [], "edits": []}

    def plan_enqueue(plan_id, *, task_id):
        row = db_session.get(AutoEditPlan, plan_id)
        assert row is not None and row.celery_task_id == task_id
        queued["plans"].append((plan_id, task_id))
        return task_id

    def edit_enqueue(edit_id, *, task_id):
        queued["edits"].append((edit_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_auto_edit_plan", plan_enqueue)
    monkeypatch.setattr(edits_api, "enqueue_clip_edit", edit_enqueue)
    return queued


def storage() -> LocalStorageProvider:
    return LocalStorageProvider(get_settings().media_root)


def clip_ctx(db, email="owner@example.com") -> dict:
    ctx = ready_clip(db, email)
    with tempfile.NamedTemporaryFile(suffix=".mp4") as clip_file:  # the rendered clip exists
        storage().put_file(Path(clip_file.name), ctx["clip"].storage_key)
    ctx["base"] = ctx["base"].removesuffix("/edits") + "/auto-edits"
    ctx["edits"] = ctx["base"].removesuffix("/auto-edits") + "/edits"
    return ctx


class Planner:
    name, model = "ollama", "llama3.2:3b"

    def __init__(self, data=GOOD):
        self.data = data

    def plan(self, context):
        return PlannerResult(parse_proposal(self.data, provider="test"), self.name, self.model)


def plan_now(db, plan_id: str, data=GOOD) -> None:
    run_auto_edit_plan(uuid.UUID(plan_id), db, planner=Planner(data), storage=storage(),
                       task_id=db.get(AutoEditPlan, uuid.UUID(plan_id)).celery_task_id)  # fmt: skip
    db.expire_all()


def with_broll(db, ctx, tmp_path) -> dict:
    """A completed B-roll suggestion and a tagged project image that matches it."""
    clip = ctx["clip"]
    config = BrollConfig.from_settings(get_settings())
    analysis = BrollAnalysis(
        clip_id=clip.id, video_id=clip.video_id, config=config.snapshot(),
        config_fingerprint=config.fingerprint(), suggestion_version=config.suggestion_version,
        provider="ollama", model=config.model, status="completed", suggestion_count=1,
    )  # fmt: skip
    db.add(analysis)
    db.flush()
    suggestion = BrollSuggestion(
        analysis_id=analysis.id, clip_id=clip.id, sequence_index=0, start_time=2.0,
        end_time=4.5, query="bridge joint", reason="Shows the joint", provider="ollama",
        provider_version="m",
    )  # fmt: skip
    key = generate_key("jpg", "visuals")
    source = tmp_path / "bridge.jpg"
    source.write_bytes(b"x")
    storage().put_file(source, key)
    asset = VisualAsset(
        project_id=ctx["video"].project_id, kind="image", display_name="bridge.jpg",
        storage_key=key, content_type="image/jpeg", file_size=1, sha256="d" * 64, width=1600,
        height=900, codec="jpeg", container="jpeg", tags=["bridge", "joint"],
    )  # fmt: skip
    db.add_all([suggestion, asset])
    db.commit()
    return {"suggestion": suggestion, "asset": asset}


def test_the_recipes_are_listed_in_order(client):
    assert client.get("/auto-edit/recipes").status_code == 401
    sign_up(client)
    recipes = client.get("/auto-edit/recipes").json()
    assert [r["name"] for r in recipes] == ["clean", "punchy", "story", "minimal"]
    assert recipes[1] == {"name": "punchy", "version": "punchy_v1", "label": "Punchy",
                          "description": recipes[1]["description"]}  # fmt: skip


def test_create_is_idempotent_per_inputs_and_commits_the_token_first(
    client, db_session, fake_queues
):
    sign_up(client)
    ctx = clip_ctx(db_session)
    first = client.post(ctx["base"], json={"recipe": "punchy"})
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "queued" and body["recipe"] == "punchy"
    assert body["recipe_version"] == "punchy_v1" and body["recipe_label"] == "Punchy"
    assert body["generation"] == 1 and body["configuration"] is None
    assert not INTERNAL & set(body)
    again = client.post(ctx["base"], json={"recipe": "punchy"})
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    other = client.post(ctx["base"], json={"recipe": "minimal"})
    assert other.status_code == 201 and other.json()["id"] != body["id"]
    assert len(fake_queues["plans"]) == 2


@pytest.mark.parametrize(
    "body",
    [{"recipe": "viral"}, {}, {"recipe": "punchy", "model": "llama3.1:70b"},
     {"recipe": "punchy", "provider": "openai"}, {"recipe": "punchy", "music_asset_id": "x"}],
)  # fmt: skip
def test_only_a_recipe_and_an_optional_track_can_be_asked_for(client, db_session, body):
    sign_up(client)
    ctx = clip_ctx(db_session)
    assert client.post(ctx["base"], json=body).status_code == 422


def test_music_must_be_this_projects_track(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    response = client.post(ctx["base"], json={"recipe": "clean",
                                              "music_asset_id": str(uuid.uuid4())})  # fmt: skip
    assert response.status_code == 409


def test_a_clip_that_is_not_ready_cannot_be_planned(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    ctx["clip"].status = "rendering"
    db_session.commit()
    assert client.post(ctx["base"], json={"recipe": "clean"}).status_code == 409


def test_a_ready_plan_reads_as_product_copy(client, db_session, tmp_path):
    sign_up(client)
    ctx = clip_ctx(db_session)
    with_broll(db_session, ctx, tmp_path)
    plan_id = client.post(ctx["base"], json={"recipe": "punchy"}).json()["id"]
    plan_now(db_session, plan_id)
    body = client.get(f"{ctx['base']}/{plan_id}").json()
    assert body["status"] == "ready" and body["progress_percent"] == 100
    assert body["configuration"]["visuals"]["elements"][0]["start_seconds"] == 2.0
    sections = body["explanations"]["sections"]
    assert set(sections) == {"layout", "captions", "hook", "visuals", "audio"}
    assert "used_suggestions" not in body["explanations"]
    assert body["confidence"]["planner"] == "local_ai" and body["confidence"]["fallback"] is False
    text = json.dumps(body)
    for leak in ("task-", "llama", "11434", "visual_asset_", "suggestion_1", "media/"):
        assert leak not in text, leak
    listed = client.get(ctx["base"]).json()["plans"]
    assert [p["id"] for p in listed] == [plan_id]


def test_changed_inputs_make_a_new_plan(client, db_session, tmp_path):
    sign_up(client)
    ctx = clip_ctx(db_session)
    first = client.post(ctx["base"], json={"recipe": "punchy"}).json()["id"]
    plan_now(db_session, first)
    with_broll(db_session, ctx, tmp_path)  # new suggestions and a matching asset
    second = client.post(ctx["base"], json={"recipe": "punchy"})
    assert second.status_code == 201 and second.json()["id"] != first


def test_apply_makes_one_normal_edit_and_never_changes_the_plan(
    client, db_session, tmp_path, fake_queues
):
    sign_up(client)
    ctx = clip_ctx(db_session)
    found = with_broll(db_session, ctx, tmp_path)
    plan_id = client.post(ctx["base"], json={"recipe": "punchy"}).json()["id"]
    assert client.post(f"{ctx['base']}/{plan_id}/apply").status_code == 409  # not ready yet
    plan_now(db_session, plan_id)
    configuration = client.get(f"{ctx['base']}/{plan_id}").json()["configuration"]
    applied = client.post(f"{ctx['base']}/{plan_id}/apply")
    assert applied.status_code == 200
    body = applied.json()
    assert body["plan"]["status"] == "applied" and body["plan"]["applied_at"]
    assert body["plan"]["clip_edit_id"] == body["edit"]["id"]
    assert body["edit"]["configuration"] == configuration  # exactly the plan's configuration
    assert body["plan"]["configuration"] == configuration
    again = client.post(f"{ctx['base']}/{plan_id}/apply")
    assert again.json()["edit"]["id"] == body["edit"]["id"]
    assert db_session.scalar(select(func.count()).select_from(ClipEdit)) == 1
    assert len(fake_queues["edits"]) == 1
    db_session.refresh(found["suggestion"])
    assert found["suggestion"].status == "accepted"  # the creator used it (history)


def test_apply_reuses_an_identical_manual_edit(client, db_session, fake_queues):
    sign_up(client)
    ctx = clip_ctx(db_session)
    plan_id = client.post(ctx["base"], json={"recipe": "minimal"}).json()["id"]
    plan_now(db_session, plan_id, data={**GOOD, "visuals": []})
    snapshot = client.get(f"{ctx['base']}/{plan_id}").json()["configuration"]
    manual = {
        "layout": snapshot["layout"], "captions_enabled": snapshot["captions"]["enabled"],
        "caption_style": snapshot["captions"]["style"],
        "caption_position": snapshot["captions"]["position"],
        "caption_timing": snapshot["captions"].get("timing"),
        "hook_enabled": True, "hook_text": snapshot["hook"]["text"],
        "hook_style": snapshot["hook"]["style"], "hook_position": snapshot["hook"]["position"],
        "hook_duration_seconds": snapshot["hook"]["duration"],
        "audio": {"source_gain_db": 0, "normalize": True, "music": None, "sfx": []},
    }  # fmt: skip
    edit = client.post(ctx["edits"], json=manual)
    assert edit.status_code == 201
    applied = client.post(f"{ctx['base']}/{plan_id}/apply").json()
    assert applied["edit"]["id"] == edit.json()["id"] and len(fake_queues["edits"]) == 1


def test_apply_checks_every_asset_again(client, db_session, tmp_path):
    sign_up(client)
    ctx = clip_ctx(db_session)
    found = with_broll(db_session, ctx, tmp_path)
    plan_id = client.post(ctx["base"], json={"recipe": "punchy"}).json()["id"]
    plan_now(db_session, plan_id)
    db_session.delete(found["asset"])
    db_session.commit()
    response = client.post(f"{ctx['base']}/{plan_id}/apply")
    assert response.status_code == 409
    assert db_session.get(AutoEditPlan, uuid.UUID(plan_id)).status == "ready"
    assert db_session.scalar(select(func.count()).select_from(ClipEdit)) == 0


def test_regenerate_keeps_history_and_waits_for_the_current_plan(client, db_session, fake_queues):
    sign_up(client)
    ctx = clip_ctx(db_session)
    first = client.post(ctx["base"], json={"recipe": "story"}).json()["id"]
    assert client.post(f"{ctx['base']}/{first}/regenerate").status_code == 409  # still queued
    plan_now(db_session, first)
    second = client.post(f"{ctx['base']}/{first}/regenerate")
    assert second.status_code == 201
    assert second.json()["generation"] == 2 and second.json()["recipe"] == "story"
    third = client.post(f"{ctx['base']}/{first}/regenerate")  # from the older plan: next gen
    assert third.json()["generation"] == 3
    ids = [p["id"] for p in client.get(ctx["base"]).json()["plans"]]
    assert ids == [third.json()["id"], second.json()["id"], first]
    assert db_session.get(AutoEditPlan, uuid.UUID(first)).status == "ready"  # untouched


def test_a_failed_plan_is_retried_with_a_fresh_token(client, db_session, fake_queues, monkeypatch):
    sign_up(client)
    ctx = clip_ctx(db_session)
    plan_id = client.post(ctx["base"], json={"recipe": "clean"}).json()["id"]
    row = db_session.get(AutoEditPlan, uuid.UUID(plan_id))
    assert client.post(f"{ctx['base']}/{plan_id}/retry").status_code == 409  # queued
    row.status, row.error_code, row.error_message = "failed", "planner_timeout", "Too slow"
    db_session.commit()
    assert client.post(ctx["base"], json={"recipe": "clean"}).status_code == 409  # use retry
    old = row.celery_task_id
    retried = client.post(f"{ctx['base']}/{plan_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["attempt"] == 2 and retried.json()["error_code"] is None
    db_session.refresh(row)
    assert row.celery_task_id != old and fake_queues["plans"][-1] == (row.id, row.celery_task_id)
    row.status, row.attempt = "failed", get_settings().auto_edit_max_attempts
    db_session.commit()
    assert client.post(f"{ctx['base']}/{plan_id}/retry").status_code == 409


def test_an_unavailable_queue_leaves_no_plan(client, db_session, monkeypatch):
    sign_up(client)
    ctx = clip_ctx(db_session)

    def down(plan_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_auto_edit_plan", down)
    assert client.post(ctx["base"], json={"recipe": "clean"}).status_code == 503
    assert db_session.scalar(select(func.count()).select_from(AutoEditPlan)) == 0


def routes(ctx, plan_id):
    base = ctx["base"]
    return [
        ("post", base, {"recipe": "clean"}),
        ("get", base, None),
        ("get", f"{base}/{plan_id}", None),
        ("post", f"{base}/{plan_id}/retry", None),
        ("post", f"{base}/{plan_id}/regenerate", None),
        ("post", f"{base}/{plan_id}/apply", None),
    ]


def test_ownership_anonymous_401_and_others_404(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    plan_id = client.post(ctx["base"], json={"recipe": "clean"}).json()["id"]
    plan_now(db_session, plan_id)
    client.post("/auth/logout")
    for method, url, body in routes(ctx, plan_id):
        kwargs = {"json": body} if body else {}
        assert getattr(client, method)(url, **kwargs).status_code == 401, url
    sign_up(client, "intruder@example.com")
    for method, url, body in routes(ctx, plan_id):
        kwargs = {"json": body} if body else {}
        assert getattr(client, method)(url, **kwargs).status_code == 404, url
    assert db_session.get(AutoEditPlan, uuid.UUID(plan_id)).status == "ready"


def test_another_clips_plan_is_404_here(client, db_session):
    sign_up(client)
    first, second = clip_ctx(db_session), clip_ctx(db_session)
    plan_id = client.post(first["base"], json={"recipe": "clean"}).json()["id"]
    assert client.get(f"{second['base']}/{plan_id}").status_code == 404
    assert client.post(f"{second['base']}/{plan_id}/apply").status_code == 404
