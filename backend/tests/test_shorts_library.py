"""The Shorts library: one honest creator-level status per Short, owner-scoped, no internals,
historical provenance, and a fixed number of queries whatever the library's size."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, select

from app.core.config import get_settings
from app.models import (
    ClipEdit,
    PerformanceSnapshot,
    PublishedContent,
    PublishJob,
    User,
)
from app.services.clip_edit.config import EditConfig
from app.services.performance.provenance import PROVENANCE_VERSION
from app.services.shorts_library import (
    Publication,
    PublishState,
    ShortStatus,
    publication,
    short_status,
)
from tests.test_auto_edit_model import make_plan, ready
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_model import make_edit

INTERNAL = ("storage_key", "celery_task_id", "fingerprint", "config", "upload_session", "scopes")
NOW = datetime.now(UTC)


def me(db, email: str) -> User:
    return db.scalar(select(User).where(User.email == email))


def _config(n: int) -> EditConfig:
    styles = ("clean", "bold", "creator")
    return EditConfig.create(
        layout=("center_crop", "blur_background", "fit")[n % 3],
        captions_enabled=True,
        caption_style=styles[(n // 3) % 3],
        caption_position="bottom",
    )


def version(db, clip, n: int = 0, *, status: str = "ready", **fields) -> ClipEdit:
    extra = (
        {"storage_key": f"edits/{uuid.uuid4()}.mp4", "file_size": 10, "duration_seconds": 21.0,
         "completed_at": NOW} if status == "ready" else {}
    )  # fmt: skip
    return make_edit(db, clip, _config(n), status=status, **{**extra, **fields})


def job(db, user: User, edit: ClipEdit, status: str, **fields) -> PublishJob:
    row = PublishJob(
        user_id=user.id, edit_id=edit.id, provider="youtube", title="Lava!", privacy="private",
        category_id="22", fingerprint=uuid.uuid4().hex + uuid.uuid4().hex, status=status, **fields,
    )  # fmt: skip
    db.add(row)
    db.commit()
    return row


def by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def test_signed_out_is_refused(client):
    client.cookies.clear()
    assert client.get("/shorts").status_code == 401
    assert client.get(f"/shorts/{uuid.uuid4()}").status_code == 401


def test_a_new_creator_has_no_shorts(client):
    sign_up(client, "fresh@example.com")
    assert client.get("/shorts").json() == {"shorts": [], "truncated": False}
    assert client.get(f"/shorts/{uuid.uuid4()}").status_code == 404


def test_every_state_reads_as_one_creator_status(client, db_session):
    sign_up(client, "maker@example.com")
    user = me(db_session, "maker@example.com")
    clips = [ready_clip(db_session, "maker@example.com")["clip"] for _ in range(8)]
    ready = version(db_session, clips[0])
    rendering = version(db_session, clips[1], status="rendering", started_at=NOW,
                        heartbeat_at=NOW)  # fmt: skip
    failed = version(db_session, clips[2], status="failed", error_code="render_failed",
                     error_message="The render failed.")  # fmt: skip
    uploading = version(db_session, clips[3])
    job(db_session, user, uploading, "uploading", started_at=NOW, heartbeat_at=NOW)
    on_youtube = version(db_session, clips[4])
    job(db_session, user, on_youtube, "uploaded", provider_video_id="abcdefghijk",
        provider_processing_status="unknown", completed_at=NOW)  # fmt: skip
    published = version(db_session, clips[5])
    job(db_session, user, published, "published", provider_video_id="lmnopqrstuv",
        published_at=NOW, completed_at=NOW)  # fmt: skip
    publish_failed = version(db_session, clips[6])
    job(db_session, user, publish_failed, "failed", error_code="network",
        error_message="The upload could not finish.")  # fmt: skip
    draft = clips[7]  # cut from a moment, no version yet

    body = client.get("/shorts").json()
    assert body["truncated"] is False
    items = by_id(body["shorts"])
    expected = {
        ready.id: ("ready", None, "not_published"),
        rendering.id: ("rendering", None, "not_published"),
        failed.id: ("failed", "render_failed", "not_published"),
        uploading.id: ("publishing", None, "uploading"),
        on_youtube.id: ("on_youtube", None, "on_youtube"),
        published.id: ("published", None, "published"),
        publish_failed.id: ("needs_attention", "publish_failed", "failed"),
        draft.id: ("draft", None, "not_published"),
    }
    assert set(items) == {str(i) for i in expected}
    for short_id, (status, reason, publish) in expected.items():
        item = items[str(short_id)]
        assert (item["status"], item["reason"], item["publish"]["state"]) == (status, reason,
                                                                              publish)  # fmt: skip
    assert items[str(draft.id)]["kind"] == "draft" and items[str(draft.id)]["version"] is None
    assert items[str(draft.id)]["preview"] == "clip"
    assert items[str(ready.id)]["preview"] == "short" and items[str(ready.id)]["kind"] == "short"
    assert items[str(rendering.id)]["preview"] == "clip"  # the cut, until the version exists
    assert items[str(ready.id)]["title"] == "That Was Crazy!"
    assert items[str(ready.id)]["duration_seconds"] == 21.0
    assert items[str(rendering.id)]["duration_seconds"] == 20.0  # the moment's length meanwhile
    # A real upload links to YouTube; dates are YouTube's, never invented.
    assert items[str(published.id)]["publish"]["video_url"] == "https://youtu.be/lmnopqrstuv"
    assert items[str(published.id)]["publish"]["published_at"] is not None
    assert items[str(on_youtube.id)]["publish"]["published_at"] is None
    assert items[str(on_youtube.id)]["publish"]["uploaded_at"] is not None
    assert items[str(ready.id)]["publish"]["video_url"] is None
    text = str(body)
    assert not any(word in text for word in INTERNAL)


def test_stalled_work_needs_attention(client, db_session):
    sign_up(client, "stalled@example.com")
    user = me(db_session, "stalled@example.com")
    long_ago = NOW - timedelta(hours=3)
    render = version(db_session, ready_clip(db_session, "stalled@example.com")["clip"],
                     status="rendering", started_at=long_ago, heartbeat_at=long_ago)  # fmt: skip
    upload = version(db_session, ready_clip(db_session, "stalled@example.com")["clip"])
    job(db_session, user, upload, "uploading", started_at=long_ago, heartbeat_at=long_ago)
    items = by_id(client.get("/shorts").json()["shorts"])
    assert items[str(render.id)]["status"] == "needs_attention"
    assert items[str(render.id)]["reason"] == "render_stalled"
    assert items[str(upload.id)]["status"] == "needs_attention"
    assert items[str(upload.id)]["reason"] == "publish_stalled"


def test_youtube_having_the_video_outranks_a_later_failed_attempt():
    settings = get_settings()
    first = PublishJob(status="published", provider_video_id="x", created_at=NOW)
    later = PublishJob(status="failed", created_at=NOW + timedelta(minutes=5))
    assert publication([later, first], settings).state == PublishState.PUBLISHED
    processing = PublishJob(status="processing", provider_video_id="y", status_checks=0)
    assert publication([processing], settings).state == PublishState.PROCESSING
    assert publication([], settings) == publication([], settings)
    assert publication([], settings).state == PublishState.NOT_PUBLISHED
    rejected = PublishJob(status="provider_failed", provider_video_id="z")
    assert publication([rejected], settings).state == PublishState.FAILED
    ready = ClipEdit(status="ready")
    for state, status in ((PublishState.PROCESSING, ShortStatus.PUBLISHING),
                          (PublishState.PREPARING, ShortStatus.PUBLISHING),
                          (PublishState.ON_YOUTUBE, ShortStatus.ON_YOUTUBE),
                          (PublishState.NOT_PUBLISHED, ShortStatus.READY)):  # fmt: skip
        assert short_status(ready, Publication(state, None), settings)[0] == status


def test_versions_are_numbered_and_a_replaced_failure_is_history(client, db_session):
    sign_up(client, "versions@example.com")
    clip = ready_clip(db_session, "versions@example.com")["clip"]
    old_failure = version(db_session, clip, 0, status="failed", error_code="render_failed",
                          created_at=NOW - timedelta(hours=2))  # fmt: skip
    first = version(db_session, clip, 1, created_at=NOW - timedelta(hours=1))
    second = version(db_session, clip, 2, created_at=NOW)
    items = by_id(client.get("/shorts").json()["shorts"])
    assert str(old_failure.id) not in items  # replaced by later versions: not a Short to fix
    assert items[str(first.id)]["version"] == {"number": 2, "count": 3}
    assert items[str(second.id)]["version"] == {"number": 3, "count": 3}
    detail = client.get(f"/shorts/{second.id}").json()
    assert [(v["number"], v["status"]) for v in detail["versions"]] == [
        (1, "failed"), (2, "ready"), (3, "ready")
    ]  # fmt: skip
    # The failure is still reachable on its own (history is kept, not hidden).
    assert client.get(f"/shorts/{old_failure.id}").json()["status"] == "failed"


def test_template_and_brand_are_what_the_short_was_made_with(client, db_session):
    sign_up(client, "brand@example.com")
    clip = ready_clip(db_session, "brand@example.com")["clip"]
    template_id = uuid.uuid4()
    made = version(db_session, clip, origin={
        "template": {"id": str(template_id), "name": "Nova Punchy", "version": 2},
        "brand": {"name": "Amine Clips"}, "auto_edit_plan_id": str(uuid.uuid4()),
    })  # fmt: skip
    plain = version(db_session, clip, 1)
    items = by_id(client.get("/shorts").json()["shorts"])
    assert items[str(made.id)]["template"] == {"id": str(template_id), "name": "Nova Punchy",
                                               "version": 2}  # fmt: skip
    assert items[str(made.id)]["brand"] == {"name": "Amine Clips"}
    assert items[str(made.id)]["auto_edit"] is True
    assert items[str(plain.id)]["template"] is None and items[str(plain.id)]["brand"] is None


def test_published_shorts_carry_reported_figures_only(client, db_session):
    sign_up(client, "figures@example.com")
    user = me(db_session, "figures@example.com")
    data = ready_clip(db_session, "figures@example.com")
    edit = version(db_session, data["clip"])
    published = job(db_session, user, edit, "published", provider_video_id="fake-00000001",
                    published_at=NOW)  # fmt: skip
    content = PublishedContent(
        user_id=user.id, project_id=data["clip"].video.project_id, edit_id=edit.id,
        publish_job_id=published.id, provider="youtube", remote_video_id="fake-00000001",
        title="Lava!", published_at=NOW, provenance={}, provenance_version=PROVENANCE_VERSION,
        analytics_complete_through=date(2026, 10, 20),
    )  # fmt: skip
    db_session.add(content)
    db_session.commit()
    [item] = client.get("/shorts").json()["shorts"]
    assert item["performance"]["views"] is None  # nothing reported yet: null, never 0
    assert item["publish"]["simulated"] is True and item["publish"]["video_url"] is None
    db_session.add(PerformanceSnapshot(content_id=content.id, source="fake", data_class="counters",
                                       observed_at=NOW, views=1320, likes=41,
                                       metric_version="youtube_views_2026_08"))  # fmt: skip
    db_session.commit()
    [item] = client.get("/shorts").json()["shorts"]
    assert item["performance"]["views"] == 1320 and item["performance"]["comments"] is None
    assert item["performance"]["simulated"] is True
    assert item["performance"]["content_id"] == str(content.id)


def test_another_creators_shorts_are_invisible(client, db_session):
    sign_up(client, "owner@example.com")
    clip = ready_clip(db_session, "owner@example.com")["clip"]
    edit = version(db_session, clip)
    client.cookies.clear()
    sign_up(client, "stranger@example.com")
    assert client.get("/shorts").json()["shorts"] == []
    assert client.get(f"/shorts/{edit.id}").status_code == 404
    assert client.get(f"/shorts/{clip.id}").status_code == 404


def test_a_draft_opens_and_its_link_follows_it_once_it_has_a_version(client, db_session):
    sign_up(client, "draft@example.com")
    clip = ready_clip(db_session, "draft@example.com")["clip"]
    make_plan(db_session, clip, **ready())
    db_session.commit()
    draft = client.get(f"/shorts/{clip.id}").json()
    assert draft["kind"] == "draft" and draft["status"] == "draft" and draft["plan_ready"] is True
    assert draft["auto_edit_plan_id"] is not None and draft["versions"] == []
    assert draft["moment"] == {"start_time": 10.0, "end_time": 30.0, "rank": 1,
                               "category": "story"}  # fmt: skip
    edit = version(db_session, clip)
    followed = client.get(f"/shorts/{clip.id}").json()
    assert followed["kind"] == "short" and followed["id"] == str(edit.id)


def test_a_failed_cut_is_a_failed_draft(client, db_session):
    sign_up(client, "cut@example.com")
    clip = ready_clip(db_session, "cut@example.com", clip_status="failed")["clip"]
    [item] = client.get("/shorts").json()["shorts"]
    assert item["id"] == str(clip.id) and item["status"] == "failed"
    assert item["reason"] == "clip_failed" and item["preview"] is None


@pytest.fixture
def statements(db_session):
    """Counts the SQL statements the API runs."""
    seen: list[str] = []
    engine = db_session.get_bind()

    def count(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    yield seen
    event.remove(engine, "before_cursor_execute", count)


def test_the_library_costs_the_same_queries_for_one_short_or_many(client, db_session, statements):
    sign_up(client, "many@example.com")
    user = me(db_session, "many@example.com")
    first = version(db_session, ready_clip(db_session, "many@example.com")["clip"])
    job(db_session, user, first, "published", provider_video_id="aaaaaaaaaaa", published_at=NOW)
    statements.clear()
    client.get("/shorts")
    one = len(statements)
    for n in range(6):
        edit = version(db_session, ready_clip(db_session, "many@example.com")["clip"], n)
        job(db_session, user, edit, "published", provider_video_id=f"bbbbbbbbbb{n}",
            published_at=NOW)  # fmt: skip
    ready_clip(db_session, "many@example.com")  # and a draft
    statements.clear()
    assert len(client.get("/shorts").json()["shorts"]) == 8
    assert len(statements) == one


def test_a_short_says_whether_performance_can_be_shown(client, db_session):
    sign_up(client, "access@example.com")
    edit = version(db_session, ready_clip(db_session, "access@example.com")["clip"])
    analytics = client.get(f"/shorts/{edit.id}").json()["analytics"]
    # No YouTube connection, and analytics switched off on this server: nothing to show.
    assert analytics["connected"] is False and analytics["analytics_access"] is False
    assert set(analytics) == {"enabled", "connected", "connection_status", "analytics_access",
                              "simulated"}  # fmt: skip


def test_home_and_the_project_speak_the_librarys_status(client, db_session):
    sign_up(client, "agree@example.com")
    user = me(db_session, "agree@example.com")
    data = ready_clip(db_session, "agree@example.com")
    first = version(db_session, data["clip"], 0)
    second = version(db_session, data["clip"], 1)
    job(db_session, user, first, "uploaded", provider_video_id="ccccccccccc",
        provider_processing_status="unknown", completed_at=NOW)  # fmt: skip
    job(db_session, user, second, "failed", error_code="network", error_message="Lost.")
    library = {item["id"]: item["status"] for item in client.get("/shorts").json()["shorts"]}
    home = {s["edit_id"]: s for s in client.get("/workspace/home").json()["recent_shorts"]}
    project_id = data["clip"].video.project_id
    recent = client.get(f"/projects/{project_id}/summary").json()["shorts"]["recent"]
    for summary in [*home.values(), *recent]:
        assert summary["short_status"] == library[summary["edit_id"]]
    assert library[str(first.id)] == "on_youtube" and home[str(first.id)]["published"] is False
    assert library[str(second.id)] == "needs_attention"
