"""Copilot actions: an allow-listed registry, labels written by PeakSift, checked when offered
and again when clicked — owner-scoped, state-aware, never destructive."""

import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.models import Clip, ClipCandidate, User
from app.services import routes
from app.services.copilot import service
from app.services.copilot.actions import offer
from app.services.copilot.context import build_context
from app.services.copilot.contract import ACTION_TYPES, ProposedAction
from app.services.copilot.provider import FakeCopilotProvider
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_model import make_edit


def me(db, email):
    return db.scalar(select(User).where(User.email == email))


def ask(db, email, project_id, actions, page="moments"):
    fake = FakeCopilotProvider([{"message": "Here you go.", "actions": actions, "references": []}])
    return service.ask(
        db,
        me(db, email),
        get_settings(),
        text="What next?",
        page=page,
        project_id=project_id,
        provider=fake,
    )


def resolve(client, message_id, index=0):
    return client.post(f"/copilot/messages/{message_id}/actions/{index}")


def test_no_action_can_publish_delete_or_change_anything():
    forbidden = ("publish", "delete", "remove", "disconnect", "render", "upload", "rename")
    verbs = {name.split("_")[0] for name in ACTION_TYPES}
    assert verbs == {"open", "new", "search", "create"} and not verbs & set(forbidden)


def test_an_offered_moment_opens_create_a_short(client, db_session):
    sign_up(client, "go@example.com")
    data = ready_clip(db_session, "go@example.com")
    clip = data["clip"]
    project_id = clip.video.project_id
    answer = ask(
        db_session,
        "go@example.com",
        project_id,
        [
            {"type": "open_editor", "handle": "moment_1"},
            {"type": "open_moments", "handle": "project"},
            {"type": "search_assets", "handle": "project", "query": "bridge joint"},
        ],
    ).answer
    assert [a["label"] for a in answer.actions] == [
        "Open the editor",
        "Review moments",
        "Search visuals for “bridge joint”",
    ]
    hrefs = [resolve(client, answer.id, i).json()["href"] for i in range(3)]
    assert hrefs == [
        routes.editor(project_id, clip.id),
        routes.project(project_id, "clips"),
        f"/projects/{project_id}/assets?q=bridge%20joint",
    ]


def test_a_moment_without_a_clip_is_offered_as_create_short(client, db_session):
    sign_up(client, "noclip@example.com")
    data = ready_clip(db_session, "noclip@example.com")
    candidate_id = data["clip"].candidate_id
    project_id = data["clip"].video.project_id
    db_session.delete(db_session.get(Clip, data["clip"].id))
    db_session.commit()
    answer = ask(
        db_session,
        "noclip@example.com",
        project_id,
        [{"type": "open_editor", "handle": "moment_1"}],
    ).answer
    assert [(a["type"], a["label"]) for a in answer.actions] == [("create_short", "Create Short")]
    body = resolve(client, answer.id).json()
    assert body["kind"] == "create_short" and body["candidate_id"] == str(candidate_id)
    assert body["project_id"] == str(project_id) and body["href"] is None


def test_actions_are_rechecked_when_clicked(client, db_session):
    sign_up(client, "stale@example.com")
    data = ready_clip(db_session, "stale@example.com")
    clip = data["clip"]
    project_id = clip.video.project_id
    edit = make_edit(
        db_session,
        clip,
        status="ready",
        storage_key=f"edits/{uuid.uuid4()}.mp4",
        file_size=10,
        duration_seconds=20.0,
    )
    db_session.commit()
    answer = ask(
        db_session,
        "stale@example.com",
        project_id,
        [
            {"type": "create_short", "handle": "moment_1"},
            {"type": "open_short", "handle": "short_1"},
        ],
        page="overview",
    ).answer
    assert resolve(client, answer.id, 1).json()["href"] == routes.editor(
        project_id, clip.id, edit_id=edit.id
    )
    db_session.delete(edit)
    candidate = db_session.get(ClipCandidate, clip.candidate_id)
    candidate.decision = "dismissed"
    db_session.commit()
    gone_moment = resolve(client, answer.id, 0)
    gone_short = resolve(client, answer.id, 1)
    assert (gone_moment.status_code, gone_moment.json()["detail"]) == (
        409,
        "This moment is no longer available.",
    )
    assert gone_short.json()["detail"] == "This Short is no longer available."


def test_dismissed_or_invented_targets_are_never_offered(client, db_session):
    sign_up(client, "drop@example.com")
    data = ready_clip(db_session, "drop@example.com")
    project_id = data["clip"].video.project_id
    candidate = db_session.get(ClipCandidate, data["clip"].candidate_id)
    user = me(db_session, "drop@example.com")
    context = build_context(db_session, user, get_settings(), page="moments", project_id=project_id)
    target = context.targets["moment_1"]
    candidate.decision = "dismissed"
    db_session.commit()
    assert offer(db_session, user, [ProposedAction("create_short", target)]) == []


def test_another_creators_actions_are_not_found(client, db_session):
    sign_up(client, "owner@example.com")
    data = ready_clip(db_session, "owner@example.com")
    answer = ask(
        db_session,
        "owner@example.com",
        data["clip"].video.project_id,
        [{"type": "create_short", "handle": "moment_1"}],
    ).answer
    assert resolve(client, answer.id, 5).status_code == 404  # no such action
    sign_up(client, "intruder@example.com")
    assert resolve(client, answer.id).status_code == 404
    assert resolve(client, uuid.uuid4()).status_code == 404


def test_repeated_labels_name_their_object(client, db_session):
    sign_up(client, "twice@example.com")
    data = ready_clip(db_session, "twice@example.com")
    project_id = data["clip"].video.project_id
    run = data["clip"].candidate.run
    db_session.add(
        ClipCandidate(
            run=run,
            video_id=data["clip"].video_id,
            start_time=40.0,
            end_time=55.0,
            duration_seconds=15.0,
            title="Second moment",
            hook="h",
            rationale="r",
            category="story",
            transcript_excerpt="x",
            overall_score=80,
            hook_score=80,
            entertainment_score=80,
            clarity_score=80,
            payoff_score=80,
            completeness_score=80,
            rank=2,
        )
    )
    db_session.commit()
    answer = ask(
        db_session,
        "twice@example.com",
        project_id,
        [
            {"type": "create_short", "handle": "moment_1"},
            {"type": "create_short", "handle": "moment_2"},
        ],
    ).answer
    assert [a["label"] for a in answer.actions] == [
        "Create Short: That Was Crazy!",
        "Create Short: Second moment",
    ]


def test_routes_escape_search_words():
    pid = uuid.uuid4()
    assert routes.assets_search(pid, "a/b?c=d") == f"/projects/{pid}/assets?q=a%2Fb%3Fc%3Dd"
    assert routes.editor(pid, pid, plan_id=pid).endswith(f"?plan={pid}")
