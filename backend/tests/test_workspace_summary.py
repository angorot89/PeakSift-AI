"""Workspace summaries for Home and the project overview: real facts from existing rows,
owner-scoped, nothing internal, the most recently active projects first."""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.models import ClipCandidate, Project, PublishedContent, PublishJob, User
from app.services.performance.provenance import PROVENANCE_VERSION
from tests.test_auto_edit_model import make_plan, ready
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_model import make_edit
from tests.test_video_upload import create_project

INTERNAL = ("storage_key", "celery_task_id", "fingerprint", "provider", "config")


def me(db, email):
    return db.scalar(select(User).where(User.email == email))


def test_signed_out_is_refused(client):
    client.cookies.clear()
    assert client.get("/workspace/home").status_code == 401


def test_an_empty_project_has_nothing_to_report(client, db_session):
    sign_up(client, "empty@example.com")
    project = create_project(client, "Fresh idea")
    body = client.get(f"/projects/{project['id']}/summary").json()
    assert body["name"] == "Fresh idea"
    assert body["source"] is None and body["transcript"] is None and body["detection"] is None
    assert body["clips"] == {
        "total": 0,
        "ready": 0,
        "working": 0,
        "failed": 0,
        "latest_ready_id": None,
    }
    assert body["shorts"]["recent"] == [] and body["plans"] == {"ready": 0, "latest_ready": None}
    assert body["published"]["uploads"] == 0 and body["published"]["last_synced_at"] is None


def test_a_worked_project_reports_each_stage(client, db_session):
    sign_up(client, "busy@example.com")
    ctx = ready_clip(db_session, "busy@example.com")
    clip = ctx["clip"]
    run = clip.candidate.run
    for rank, decision in ((2, "dismissed"), (3, "saved"), (4, "undecided")):
        db_session.add(ClipCandidate(
            run=run, video_id=clip.video_id, start_time=40.0, end_time=55.0,
            duration_seconds=15.0, title=f"Moment {rank}", hook="h", rationale="r",
            category="insight", transcript_excerpt="x", overall_score=70, hook_score=70,
            entertainment_score=70, clarity_score=70, payoff_score=70, completeness_score=70,
            rank=rank, decision=decision,
        ))  # fmt: skip
    done = make_edit(db_session, clip, status="ready", storage_key=f"edits/{uuid.uuid4()}.mp4",
                     file_size=10, duration_seconds=20.0)  # fmt: skip
    make_edit(db_session, clip, status="rendering", config_fingerprint="b" * 64)
    make_plan(db_session, clip, **ready())
    db_session.add(PublishJob(
        user_id=me(db_session, "busy@example.com").id, edit_id=done.id, provider="youtube",
        title="t", privacy="private", category_id="22", fingerprint="c" * 64, status="uploaded",
        provider_video_id="abc123xyz", completed_at=datetime.now(UTC),
    ))  # fmt: skip
    project_id = clip.video.project_id
    db_session.add(PublishedContent(
        user_id=me(db_session, "busy@example.com").id, project_id=project_id, provider="youtube",
        remote_video_id="abc123xyz", title="t", published_at=datetime.now(UTC),
        provenance={}, provenance_version=PROVENANCE_VERSION,
        analytics_complete_through=date(2026, 10, 20), last_synced_at=datetime.now(UTC),
    ))  # fmt: skip
    db_session.commit()

    response = client.get(f"/projects/{project_id}/summary")
    body = response.json()
    assert body["source"]["status"] == "ready" and body["source"]["filename"] == "s.mp4"
    assert body["transcript"]["status"] == "completed"
    detection = body["detection"]
    assert (detection["status"], detection["candidates"], detection["undecided"]) == (
        "completed",
        4,
        2,
    )
    assert (detection["saved"], detection["dismissed"]) == (1, 1)
    assert [c["rank"] for c in detection["top"]] == [1, 3, 4]  # dismissed ones are left out
    assert body["clips"]["ready"] == 1 and body["clips"]["latest_ready_id"] == str(clip.id)
    shorts = body["shorts"]
    assert (shorts["total"], shorts["ready"], shorts["working"]) == (2, 1, 1)
    assert {s["status"] for s in shorts["recent"]} == {"ready", "rendering"}
    assert shorts["recent"][0]["clip_title"] in ("That Was Crazy!",)
    assert {s["layout"] for s in shorts["recent"]} == {"blur_background"}
    assert {s["caption_style"] for s in shorts["recent"]} == {"bold"}
    assert body["plans"]["ready"] == 1 and body["plans"]["latest_ready"]["clip_id"] == str(clip.id)
    assert body["published"]["uploads"] == 1 and body["published"]["with_analytics"] == 1
    for internal in INTERNAL:
        assert f'"{internal}"' not in response.text


def test_home_lists_the_most_recently_active_projects_and_ready_shorts(client, db_session):
    sign_up(client, "home@example.com")
    quiet = create_project(client, "Quiet")
    ctx = ready_clip(db_session, "home@example.com")
    make_edit(db_session, ctx["clip"], status="ready", storage_key=f"edits/{uuid.uuid4()}.mp4",
              file_size=10, duration_seconds=20.0)  # fmt: skip
    make_edit(db_session, ctx["clip"], status="failed", error_code="x", error_message="y",
              config_fingerprint="d" * 64)  # fmt: skip
    old = db_session.get(Project, uuid.UUID(quiet["id"]))
    old.updated_at = old.created_at = datetime.now(UTC) - timedelta(days=30)
    db_session.commit()
    body = client.get("/workspace/home").json()
    assert body["project_count"] == 2
    assert [p["name"] for p in body["projects"]] == ["Stream", "Quiet"]  # recent activity first
    [short] = body["recent_shorts"]  # only finished shorts
    assert short["status"] == "ready" and short["project_name"] == "Stream"
    assert short["clip_title"] == "That Was Crazy!"


def test_summaries_are_private(client, db_session):
    sign_up(client, "owner@example.com")
    ctx = ready_clip(db_session, "owner@example.com")
    project_id = ctx["clip"].video.project_id
    sign_up(client, "someone@example.com")
    assert client.get(f"/projects/{project_id}/summary").status_code == 404
    body = client.get("/workspace/home").json()
    assert body["projects"] == [] and body["recent_shorts"] == [] and body["project_count"] == 0
