"""Copilot conversations: one per creator and project (or workspace), only what the creator saw,
bounded, clearable without touching the project, deleted with the project or the user."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import CopilotMessage, CopilotThread, Project, User
from app.services.copilot import history
from tests.test_clip_edit_api import sign_up
from tests.test_video_upload import create_project


def me(db, email):
    return db.scalar(select(User).where(User.email == email))


def test_one_thread_per_project_and_one_for_the_workspace(client, db_session):
    sign_up(client, "threads@example.com")
    user = me(db_session, "threads@example.com")
    project = create_project(client, "Bridge Lab")
    pid = uuid.UUID(project["id"])
    workspace = history.get_or_create_thread(db_session, user.id, None)
    scoped = history.get_or_create_thread(db_session, user.id, pid)
    assert workspace.id != scoped.id
    assert history.get_or_create_thread(db_session, user.id, None).id == workspace.id
    assert history.get_or_create_thread(db_session, user.id, pid).id == scoped.id
    db_session.commit()
    db_session.add(CopilotThread(user_id=user.id, project_id=None))
    with pytest.raises(IntegrityError):  # the database enforces one workspace thread too
        db_session.flush()
    db_session.rollback()


def test_messages_keep_order_and_only_what_the_creator_saw(client, db_session):
    sign_up(client, "order@example.com")
    user = me(db_session, "order@example.com")
    thread = history.get_or_create_thread(db_session, user.id, None)
    history.append(db_session, thread, role="user", content="What should I do next?", page="home")
    history.append(
        db_session,
        thread,
        role="assistant",
        content="Upload your first video.",
        page="home",
        suggestion="Start with a short recording.",
        status="ok",
        actions=[{"type": "new_project", "label": "Create a project", "target": None}],
        refs=[{"kind": "workspace", "label": "Your workspace"}],
    )
    db_session.commit()
    rows = history.messages(db_session, thread)
    assert [(m.sequence, m.role) for m in rows] == [(1, "user"), (2, "assistant")]
    assert rows[1].actions[0]["label"] == "Create a project"
    columns = set(CopilotMessage.__table__.columns.keys())
    assert not columns & {"prompt", "reasoning", "context", "raw"}  # never stored


def test_threads_are_bounded_and_prompts_see_only_recent_answers(client, db_session, monkeypatch):
    monkeypatch.setattr(history, "MAX_MESSAGES", 6)
    sign_up(client, "bounded@example.com")
    user = me(db_session, "bounded@example.com")
    thread = history.get_or_create_thread(db_session, user.id, None)
    for n in range(10):
        history.append(db_session, thread, role="user", content=f"question {n}", page="home")
        history.append(
            db_session,
            thread,
            role="assistant",
            content=f"answer {n}",
            page="home",
            status="unavailable" if n == 9 else "ok",
        )
    db_session.commit()
    count = db_session.scalar(
        select(func.count())
        .select_from(CopilotMessage)
        .where(CopilotMessage.thread_id == thread.id)
    )
    assert count == 6
    turns = history.prompt_turns(db_session, thread)
    assert turns[-1] == {
        "role": "user",
        "content": "question 9",
    }  # the unavailable answer is left out
    assert len(turns) <= history.PROMPT_TURNS


def test_reading_and_clearing_a_conversation(client, db_session):
    sign_up(client, "clear@example.com")
    user = me(db_session, "clear@example.com")
    project = create_project(client, "Clear me")
    pid = uuid.UUID(project["id"])
    thread = history.get_or_create_thread(db_session, user.id, pid)
    history.append(db_session, thread, role="user", content="Hi", page="overview")
    db_session.commit()
    body = client.get("/copilot/thread", params={"project_id": project["id"]}).json()
    assert body["scope"] == "Clear me" and [m["content"] for m in body["messages"]] == ["Hi"]
    assert body["messages"][0]["actions"] == [] and body["messages"][0]["references"] == []
    assert client.get("/copilot/thread").json() == {"scope": "Your workspace", "messages": []}
    assert client.delete("/copilot/thread", params={"project_id": project["id"]}).status_code == 204
    assert (
        client.get("/copilot/thread", params={"project_id": project["id"]}).json()["messages"] == []
    )
    assert db_session.get(Project, pid) is not None  # the project is untouched
    assert client.delete("/copilot/thread").status_code == 204  # clearing nothing is fine


def test_conversations_are_private_and_follow_their_project(client, db_session):
    sign_up(client, "private@example.com")
    owner = me(db_session, "private@example.com")
    project = create_project(client, "Mine")
    pid = uuid.UUID(project["id"])
    history.append(
        db_session,
        history.get_or_create_thread(db_session, owner.id, pid),
        role="user",
        content="secret plan",
        page="overview",
    )
    db_session.commit()
    sign_up(client, "intruder@example.com")
    assert client.get("/copilot/thread", params={"project_id": str(pid)}).status_code == 404
    assert client.delete("/copilot/thread", params={"project_id": str(pid)}).status_code == 404
    assert client.get("/copilot/thread").json()["messages"] == []
    db_session.delete(db_session.get(Project, pid))  # deleting the project deletes its thread
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(CopilotThread)) == 0
    assert db_session.scalar(select(func.count()).select_from(CopilotMessage)) == 0


def test_signed_out_is_refused(client):
    client.cookies.clear()
    assert client.get("/copilot/thread").status_code == 401
    assert client.delete("/copilot/thread").status_code == 401
