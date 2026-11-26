"""The next best action (V1.6): one deterministic rule set for Home, the Overview and the
Copilot — the same cases V1.5 tested in the frontend, now at the source of truth."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.next_action import continue_items, next_action

P = uuid.uuid4()
CLIP = uuid.uuid4()
EDIT = uuid.uuid4()
MOMENT = uuid.uuid4()
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def project(**overrides):
    base = {
        "id": P,
        "name": "Bridge Lab",
        "last_activity_at": NOW,
        "source": None,
        "transcript": None,
        "detection": None,
        "clips": {"total": 0, "ready": 0, "working": 0, "failed": 0, "latest_ready_id": None},
        "shorts": {"total": 0, "ready": 0, "working": 0, "failed": 0, "recent": []},
        "plans": {"ready": 0, "latest_ready": None},
        "published": {
            "uploads": 0,
            "working": 0,
            "failed": 0,
            "with_analytics": 0,
            "last_synced_at": None,
        },
    }
    return {**base, **overrides}


READY = {"id": uuid.uuid4(), "filename": "talk.mp4", "status": "ready", "duration_seconds": 3600}
TRANSCRIBED = {"source": READY, "transcript": {"status": "completed", "progress_percent": 100}}


def detected(candidates, undecided=None):
    return {
        **TRANSCRIBED,
        "detection": {
            "run_id": uuid.uuid4(),
            "status": "completed",
            "candidates": candidates,
            "undecided": candidates if undecided is None else undecided,
            "saved": 0,
            "dismissed": 0,
            "top": [{"id": MOMENT}] if candidates else [],
        },
    }


def short(status):
    return {"edit_id": EDIT, "clip_id": CLIP, "clip_title": "The joint", "status": status}


def shorts(*recent):
    return {
        "total": len(recent),
        "ready": sum(s["status"] == "ready" for s in recent),
        "working": 0,
        "failed": 0,
        "recent": list(recent),
    }


def published(uploads=0, working=0, failed=0, analytics=0):
    return {
        "uploads": uploads,
        "working": working,
        "failed": failed,
        "with_analytics": analytics,
        "last_synced_at": None,
    }


PLAN = {"ready": 1, "latest_ready": {"plan_id": uuid.uuid4(), "clip_id": CLIP, "recipe": "punchy"}}
CLIP_READY = {"total": 1, "ready": 1, "working": 0, "failed": 0, "latest_ready_id": CLIP}

CASES = [
    ("no source", {}, "upload", f"/projects/{P}/source"),
    (
        "unreadable source",
        {"source": {**READY, "status": "failed"}},
        "source-failed",
        f"/projects/{P}/source",
    ),
    (
        "reading the file",
        {"source": {**READY, "status": "processing_metadata"}},
        "source-working",
        f"/projects/{P}/source",
    ),
    ("not transcribed", {"source": READY}, "transcribe", f"/projects/{P}/source"),
    (
        "transcribing",
        {"source": READY, "transcript": {"status": "transcribing"}},
        "transcribing",
        f"/projects/{P}/source",
    ),
    (
        "transcript failed",
        {"source": READY, "transcript": {"status": "failed"}},
        "transcript-failed",
        f"/projects/{P}/source",
    ),
    ("transcript ready", TRANSCRIBED, "find-clips", f"/projects/{P}/clips"),
    (
        "finding",
        {**TRANSCRIBED, "detection": {**detected(0)["detection"], "status": "analyzing"}},
        "finding",
        f"/projects/{P}/clips",
    ),
    ("nothing found", detected(0), "no-moments", f"/projects/{P}/clips"),
    ("moments", detected(3), "review-clips", f"/projects/{P}/clips"),
    (
        "clip ready",
        {**detected(3), "clips": CLIP_READY},
        "create-short",
        f"/projects/{P}/clips/{CLIP}/create",
    ),
    (
        "draft ready",
        {**detected(3), "plans": PLAN},
        "plan-ready",
        f"/projects/{P}/clips/{CLIP}/auto-edit",
    ),
    (
        "draft used through the editor, Short published",
        {**detected(3), "plans": PLAN, "shorts": shorts(short("ready")), "published": published(1)},
        "published",
        f"/projects/{P}/analytics",
    ),
    (
        "rendering",
        {**detected(3), "shorts": shorts(short("rendering"))},
        "rendering",
        f"/projects/{P}/clips/{CLIP}",
    ),
    (
        "short failed",
        {**detected(3), "shorts": shorts(short("failed"))},
        "short-failed",
        f"/projects/{P}/clips/{CLIP}",
    ),
    (
        "short ready",
        {**detected(3), "shorts": shorts(short("ready"))},
        "short-ready",
        f"/shorts/{EDIT}",
    ),
    (
        "upload failed",
        {**detected(3), "shorts": shorts(short("ready")), "published": published(failed=1)},
        "upload-failed",
        f"/shorts/{EDIT}",
    ),
    (
        "uploading",
        {**detected(3), "shorts": shorts(short("ready")), "published": published(working=1)},
        "uploading",
        f"/shorts/{EDIT}",
    ),
    (
        "analytics without a job",
        {
            **detected(3),
            "shorts": shorts(short("ready")),
            "published": published(failed=1, analytics=3),
        },
        "published",
        f"/projects/{P}/analytics",
    ),
    (
        "published",
        {**detected(3), "shorts": shorts(short("ready")), "published": published(uploads=1)},
        "published",
        f"/projects/{P}/analytics",
    ),
]


@pytest.mark.parametrize(("name", "state", "key", "href"), CASES, ids=[c[0] for c in CASES])
def test_each_state_has_one_next_step(name, state, key, href):
    step = next_action(project(**state))
    assert (step.key, step.href) == (key, href)


def test_steps_speak_plainly_and_ask_nothing_while_peaksift_works():
    waiting = next_action(project(source=READY, transcript={"status": "transcribing"}))
    assert waiting.cta is None and waiting.tone == "waiting"
    assert next_action(project(**detected(1))).title == "1 moment ready to review"
    assert next_action(project(**detected(4, 2))).title == "2 moments ready to review"
    for _, state, _, _ in CASES:
        text = " ".join(str(v) for v in next_action(project(**state)).read().values() if v)
        for word in ("celery", "provider", "candidate", "fingerprint", "embedding", "None"):
            assert word not in text


def test_every_step_names_the_copilot_action_that_opens_it():
    for _, state, _, _ in CASES:
        step = next_action(project(**state))
        assert step.action["type"] and step.action["kind"] in {"project", "clip", "short", "moment"}
    assert next_action(project(**detected(3))).action == {
        "type": "create_short",
        "kind": "moment",
        "id": MOMENT,
    }
    assert next_action(project(**{**detected(3), "clips": CLIP_READY})).action == {
        "type": "open_create",
        "kind": "clip",
        "id": CLIP,
    }


def test_continue_working_puts_problems_first_then_the_most_recent():
    items = continue_items(
        [
            project(id=uuid.uuid4(), name="Calm", last_activity_at=NOW, **detected(2)),
            project(
                id=uuid.uuid4(),
                name="Broken",
                last_activity_at=NOW - timedelta(days=1),
                source={**READY, "status": "failed"},
            ),
            project(
                id=uuid.uuid4(),
                name="Older",
                last_activity_at=NOW - timedelta(days=2),
                **TRANSCRIBED,
            ),
        ]
    )
    assert [i["project_name"] for i in items] == ["Broken", "Calm", "Older"]
    assert items[0]["tone"] == "attention" and set(items[0]) >= {"key", "href", "project_id"}


def test_the_api_serves_the_same_step(client, db_session):
    from tests.test_clip_edit_api import ready_clip, sign_up

    sign_up(client, "engine@example.com")
    data = ready_clip(db_session, "engine@example.com")
    project_id = data["clip"].video.project_id
    summary = client.get(f"/projects/{project_id}/summary").json()
    assert summary["next_action"]["key"] == "create-short"
    assert summary["next_action"]["href"].endswith(f"/clips/{data['clip'].id}/create")
    home = client.get("/workspace/home").json()
    assert home["continue_items"][0]["key"] == "create-short"
    assert home["continue_items"][0]["project_id"] == str(project_id)


def test_the_copilot_recommends_the_same_step_even_offline(client, db_session):
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import User
    from app.services.copilot import service
    from app.services.copilot.provider import CopilotProviderError, FakeCopilotProvider
    from tests.test_clip_edit_api import ready_clip, sign_up

    sign_up(client, "same@example.com")
    data = ready_clip(db_session, "same@example.com")
    project_id = data["clip"].video.project_id
    user = db_session.scalar(select(User).where(User.email == "same@example.com"))
    dashboard = client.get(f"/projects/{project_id}/summary").json()["next_action"]

    def ask(text, provider):
        return service.ask(
            db_session,
            user,
            get_settings(),
            text=text,
            page="overview",
            project_id=project_id,
            provider=provider,
        ).answer

    never = FakeCopilotProvider([AssertionError("the model must not decide the workflow")])
    own = ask("What should I do next?", never)  # answered by PeakSift itself
    offline = ask(
        "Help me with this project",
        FakeCopilotProvider([CopilotProviderError("unavailable", "down")]),
    )
    assert own.status == "ok" and own.content == f"{dashboard['title']}. {dashboard['description']}"
    assert never.calls == []
    assert offline.status == "unavailable" and offline.content == service.UNAVAILABLE
    for answer in (own, offline):
        href = client.post(f"/copilot/messages/{answer.id}/actions/0").json()["href"]
        assert href == dashboard["href"]


def test_quick_start_says_moments_follow_the_transcript():
    """Dropped on Home: the creator is told they do not have to come back and press anything."""
    plain = next_action(project(source=READY, transcript={"status": "transcribing"}))
    quick = next_action(
        project(source=READY, transcript={"status": "transcribing", "auto_find_moments": True})
    )
    assert (plain.key, quick.key) == ("transcribing", "transcribing")
    assert "finds your moments" not in plain.description
    assert "finds your moments" in quick.description
    assert quick.tone == "waiting"
