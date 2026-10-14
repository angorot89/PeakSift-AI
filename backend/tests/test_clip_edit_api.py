import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.api import clip_edits as api
from app.core.config import get_settings
from app.models import (
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    Project,
    Transcription,
    TranscriptSegment,
    User,
    Video,
)
from app.services.clip_edit.storage import EditArtifactStore
from app.services.clip_render.storage import clip_storage_key
from app.services.storage import LocalMediaStorage
from app.workers.dispatch import JobQueueUnavailable

PASSWORD = "correct horse battery"
CONTENT = bytes(range(256)) * 16  # 4096 distinguishable bytes
EDIT_KEYS = {
    "id",
    "clip_id",
    "video_id",
    "status",
    "progress_percent",
    "attempt",
    "is_stale",
    "configuration",
    "aspect_ratio",
    "layout",
    "captions_enabled",
    "caption_style",
    "caption_position",
    "reframe_analysis_id",
    "focus_x",
    "focus_y",
    "caption_renderer",
    "caption_timing",
    "caption_track_id",
    "hook_enabled",
    "hook_text",
    "hook_style",
    "hook_position",
    "hook_duration_seconds",
    "output_width",
    "output_height",
    "render_profile",
    "caption_cue_count",
    "duration_seconds",
    "width",
    "height",
    "fps",
    "file_size",
    "video_codec",
    "audio_codec",
    "error_code",
    "error_message",
    "created_at",
    "started_at",
    "completed_at",
}


@pytest.fixture
def storage() -> LocalMediaStorage:
    return LocalMediaStorage(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalMediaStorage):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch, db_session):
    """Never run real renders; prove the attempt token is committed before enqueue."""
    queued: list[tuple[uuid.UUID, str]] = []

    def fake_enqueue(edit_id, *, task_id):
        row = db_session.get(ClipEdit, edit_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append((edit_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_clip_edit", fake_enqueue)
    monkeypatch.setattr(api, "supports_captions", lambda path: True)
    return queued


def sign_up(client: TestClient, email: str = "owner@example.com") -> None:
    assert (
        client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )


def ready_clip(
    db_session: Session, email: str, *, transcript: bool = True, clip_status: str = "ready"
) -> dict:
    user = db_session.scalar(select(User).where(User.email == email))
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="s.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=1,
        status="ready",
        duration_seconds=60.0,
    )
    transcription = Transcription(
        video=video, provider="f", model="f", status="completed" if transcript else "transcribing"
    )
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=10.0, end_time=14.0, text="hello there")
    )
    run = ClipDetectionRun(
        video=video,
        transcription=transcription,
        transcript_fingerprint="f" * 64,
        provider="o",
        model="m",
        config={},
        status="completed",
    )
    db_session.add_all([project, video, transcription, run])
    db_session.flush()
    candidate = ClipCandidate(
        run=run,
        video_id=video.id,
        start_time=10.0,
        end_time=30.0,
        duration_seconds=20.0,
        title="That Was Crazy!",
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
        rank=1,
    )
    clip = Clip(
        candidate=candidate,
        video_id=video.id,
        start_time=10.0,
        end_time=30.0,
        duration_seconds=20.0,
        status=clip_status,
    )
    db_session.add_all([candidate, clip])
    db_session.flush()
    clip.storage_key = clip_storage_key(clip.id)
    db_session.commit()
    base = f"/projects/{project.id}/videos/{video.id}/clips/{clip.id}/edits"
    return {"base": base, "clip": clip, "video": video}


BLUR_BOLD = {
    "layout": "blur_background",
    "captions_enabled": True,
    "caption_style": "bold",
    "caption_position": "bottom",
}


def mark_ready(db_session: Session, storage: LocalMediaStorage, edit_id: str) -> ClipEdit:
    edit = db_session.get(ClipEdit, uuid.UUID(edit_id))
    store = EditArtifactStore(storage)
    store.workspace(edit.id, edit.attempt)
    store.render_path(edit.id, edit.attempt).write_bytes(CONTENT)
    edit.storage_key = store.finalize(edit.id, edit.attempt)
    edit.status, edit.progress_percent, edit.file_size = "ready", 100, len(CONTENT)
    edit.width, edit.height, edit.duration_seconds, edit.video_codec, edit.audio_codec = (
        1080,
        1920,
        20.0,
        "h264",
        "aac",
    )
    db_session.commit()
    return edit


# --- auth and ownership -----


def test_all_endpoints_require_authentication(client: TestClient):
    ids = [str(uuid.uuid4()) for _ in range(4)]
    base = f"/projects/{ids[0]}/videos/{ids[1]}/clips/{ids[2]}/edits"
    assert client.post(base, json=BLUR_BOLD).status_code == 401
    assert client.get(base).status_code == 401
    assert client.get(f"{base}/{ids[3]}").status_code == 401
    assert client.post(f"{base}/{ids[3]}/retry").status_code == 401
    assert client.get(f"/edits/{ids[3]}/content").status_code == 401
    assert client.get(f"/edits/{ids[3]}/download").status_code == 401


def test_other_user_gets_404_everywhere(client, db_session, storage):
    sign_up(client, "alice@example.com")
    ctx = ready_clip(db_session, "alice@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    mark_ready(db_session, storage, edit_id)
    client.cookies.clear()
    sign_up(client, "bob@example.com")

    assert client.post(ctx["base"], json=BLUR_BOLD).status_code == 404
    assert client.get(ctx["base"]).status_code == 404
    assert client.get(f"{ctx['base']}/{edit_id}").status_code == 404
    assert client.post(f"{ctx['base']}/{edit_id}/retry").status_code == 404
    for url in (f"/edits/{edit_id}/content", f"/edits/{edit_id}/download"):
        response = client.get(url)
        assert response.status_code == 404 and CONTENT[:16] not in response.content


def test_edit_reached_through_another_clip_is_404(client, db_session):
    sign_up(client)
    first, second = (
        ready_clip(db_session, "owner@example.com"),
        ready_clip(db_session, "owner@example.com"),
    )
    edit_id = client.post(first["base"], json=BLUR_BOLD).json()["id"]
    assert client.get(f"{second['base']}/{edit_id}").status_code == 404
    assert client.post(f"{second['base']}/{edit_id}/retry").status_code == 404


# --- create, normalize, deduplicate -----


def test_create_queues_an_edit_with_a_normalized_snapshot(client, db_session, fake_queue):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")

    response = client.post(ctx["base"], json=BLUR_BOLD)

    assert response.status_code == 201
    data = response.json()
    assert set(data) == EDIT_KEYS
    assert data["status"] == "queued" and data["progress_percent"] == 0 and data["attempt"] == 1
    assert data["configuration"] == {
        "version": 1,
        "aspect_ratio": "9:16",
        "layout": "blur_background",
        "output": {"width": 1080, "height": 1920},
        "captions": {"enabled": True, "style": "bold", "position": "bottom"},
    }
    assert (data["output_width"], data["output_height"]) == (1080, 1920)
    assert data["render_profile"] == "vertical_1080x1920_v1"
    for leak in ("storage_key", "celery_task_id", "captions.ass", "work-", "edits/"):
        assert leak not in response.text
    assert len(fake_queue) == 1


def test_identical_and_equivalent_requests_reuse_one_edit(client, db_session, fake_queue):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    first = client.post(ctx["base"], json=BLUR_BOLD)
    again = client.post(ctx["base"], json=BLUR_BOLD)
    assert (
        first.status_code == 201
        and again.status_code == 200
        and again.json()["id"] == first.json()["id"]
    )

    off_a = client.post(
        ctx["base"],
        json={"layout": "center_crop", "captions_enabled": False, "caption_style": "creator"},
    )
    off_b = client.post(ctx["base"], json={"layout": "center_crop"})
    assert (
        off_a.status_code == 201
        and off_b.status_code == 200
        and off_b.json()["id"] == off_a.json()["id"]
    )

    defaults = client.post(
        ctx["base"], json={"layout": "blur_background", "captions_enabled": True}
    )
    assert (
        defaults.status_code == 200 and defaults.json()["id"] == first.json()["id"]
    )  # bold/bottom defaults
    assert len(fake_queue) == 2
    assert db_session.scalar(select(func.count()).select_from(ClipEdit)) == 2


def test_a_changed_configuration_creates_a_new_variant(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    a = client.post(ctx["base"], json=BLUR_BOLD).json()
    b = client.post(
        ctx["base"],
        json={
            "layout": "center_crop",
            "captions_enabled": True,
            "caption_style": "clean",
            "caption_position": "center",
        },
    ).json()
    assert a["id"] != b["id"]
    page = client.get(ctx["base"]).json()
    assert page["total"] == 2 and {e["layout"] for e in page["edits"]} == {
        "blur_background",
        "center_crop",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"layout": "stretch"},
        {"layout": "center_crop", "aspect_ratio": "16:9"},
        {"layout": "center_crop", "captions_enabled": True, "caption_style": "comic"},
        {"layout": "center_crop", "captions_enabled": True, "caption_position": "left"},
        {"layout": "center_crop", "filter": "drawtext=text=x"},
        {"layout": "center_crop", "font": "/etc/passwd"},
        {"layout": "center_crop", "url": "http://evil.example/x"},
        {"layout": "scale=iw*2:ih*2"},
        {"captions_enabled": True},
        {"layout": "center_crop", "captions_enabled": "yes"},
    ],
)
def test_only_allow_listed_options_are_accepted(client, db_session, body):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    response = client.post(ctx["base"], json=body)
    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(ClipEdit)) == 0


def test_clip_must_be_ready(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com", clip_status="rendering")
    response = client.post(ctx["base"], json=BLUR_BOLD)
    assert response.status_code == 409 and "Generate the clip" in response.json()["detail"]


def test_captions_need_a_completed_transcript_but_plain_edits_do_not(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com", transcript=False)
    response = client.post(ctx["base"], json=BLUR_BOLD)
    assert response.status_code == 409 and "completed transcript" in response.json()["detail"]
    assert client.post(ctx["base"], json={"layout": "blur_background"}).status_code == 201


def test_captions_refused_when_ffmpeg_has_no_libass(client, db_session, monkeypatch):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    monkeypatch.setattr(api, "supports_captions", lambda path: False)
    response = client.post(ctx["base"], json=BLUR_BOLD)
    assert response.status_code == 409
    assert response.json()["detail"] == "Captions are not available on this server"
    assert client.post(ctx["base"], json={"layout": "center_crop"}).status_code == 201


def test_concurrent_identical_requests_return_the_winner(client, db_session, monkeypatch):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    real = api._existing
    calls = {"n": 0}

    def racy(db, clip, fingerprint):
        calls["n"] += 1
        if calls["n"] == 1:
            from app.services.clip_edit.config import EditConfig

            config = EditConfig.create(**BLUR_BOLD)
            db.add(
                ClipEdit(
                    clip_id=clip.id,
                    video_id=clip.video_id,
                    config=config.snapshot(),
                    config_fingerprint=fingerprint,
                    aspect_ratio="9:16",
                    layout="blur_background",
                    captions_enabled=True,
                    caption_style="bold",
                    caption_position="bottom",
                    caption_renderer="caption_v1",
                    output_width=1080,
                    output_height=1920,
                    render_profile="vertical_1080x1920_v1",
                    celery_task_id="winner",
                )
            )
            db.commit()  # the other tab's request commits first
            return None
        return real(db, clip, fingerprint)

    monkeypatch.setattr(api, "_existing", racy)
    response = client.post(ctx["base"], json=BLUR_BOLD)
    assert response.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(ClipEdit)) == 1


def test_queue_outage_leaves_no_row(client, db_session, monkeypatch):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")

    def down(edit_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_clip_edit", down)
    assert client.post(ctx["base"], json=BLUR_BOLD).status_code == 503
    assert client.get(ctx["base"]).json()["total"] == 0


# --- status and retry -----


def test_status_reports_progress_and_staleness(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    edit = db_session.get(ClipEdit, uuid.UUID(edit_id))
    edit.status, edit.progress_percent = "rendering", 15
    edit.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=get_settings().clip_render_stale_after_seconds + 5
    )
    db_session.commit()
    data = client.get(f"{ctx['base']}/{edit_id}").json()
    assert (
        data["status"] == "rendering"
        and data["progress_percent"] == 15
        and data["is_stale"] is True
    )


def test_failed_edit_needs_retry_which_issues_a_new_token(client, db_session, fake_queue):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    edit = db_session.get(ClipEdit, uuid.UUID(edit_id))
    old_token = edit.celery_task_id
    edit.status, edit.error_code, edit.error_message = (
        "failed",
        "ffmpeg_failed",
        "Rendering failed (ffmpeg exit code 1)",
    )
    db_session.commit()

    assert (
        client.post(ctx["base"], json=BLUR_BOLD).status_code == 409
    )  # create does not silently rerun
    response = client.post(f"{ctx['base']}/{edit_id}/retry")
    assert response.status_code == 200
    data = response.json()
    assert (
        data["id"] == edit_id
        and data["status"] == "queued"
        and data["attempt"] == 2
        and data["error_code"] is None
    )
    db_session.refresh(edit)
    assert edit.celery_task_id != old_token and fake_queue[-1] == (edit.id, edit.celery_task_id)


def test_retry_refuses_live_ready_and_exhausted_edits(client, db_session, storage):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    assert client.post(f"{ctx['base']}/{edit_id}/retry").status_code == 409  # queued
    edit = mark_ready(db_session, storage, edit_id)
    assert client.post(f"{ctx['base']}/{edit_id}/retry").status_code == 409  # ready
    edit.status, edit.attempt = "failed", get_settings().clip_render_max_attempts
    db_session.commit()
    response = client.post(f"{ctx['base']}/{edit_id}/retry")
    assert response.status_code == 409 and "too many times" in response.json()["detail"]


def test_retry_locks_the_row_so_concurrent_retries_serialize(client, db_session, fake_queue):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    db_session.get(ClipEdit, uuid.UUID(edit_id)).status = "failed"
    db_session.commit()
    statements: list[str] = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        assert client.post(f"{ctx['base']}/{edit_id}/retry").status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert any("FROM clip_edits" in s and "FOR UPDATE" in s for s in statements)
    # The second retry (what a concurrent one sees once the lock is released) is refused.
    assert client.post(f"{ctx['base']}/{edit_id}/retry").status_code == 409
    assert [q for q in fake_queue if q[0] == uuid.UUID(edit_id)] == fake_queue[-2:]
    assert len([q for q in fake_queue if q[0] == uuid.UUID(edit_id)]) == 2  # create + 1 retry


def test_retry_when_queue_is_down_marks_failed(client, db_session, monkeypatch):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    db_session.get(ClipEdit, uuid.UUID(edit_id)).status = "failed"
    db_session.commit()

    def down(edit_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_clip_edit", down)
    assert client.post(f"{ctx['base']}/{edit_id}/retry").status_code == 503
    assert client.get(f"{ctx['base']}/{edit_id}").json()["error_code"] == "queue_unavailable"


def test_ready_edit_with_missing_file_becomes_retryable(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    edit = db_session.get(ClipEdit, uuid.UUID(edit_id))
    edit.status, edit.storage_key = "ready", f"edits/{edit.id}/edited.mp4"  # file never written
    db_session.commit()
    data = client.get(f"{ctx['base']}/{edit_id}").json()
    assert data["status"] == "failed" and data["error_code"] == "artifact_missing"
    assert client.post(f"{ctx['base']}/{edit_id}/retry").status_code == 200


# --- private media -----


def test_preview_streams_privately_with_range_support(client, db_session, storage):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    mark_ready(db_session, storage, edit_id)

    full = client.get(f"/edits/{edit_id}/content")
    assert full.status_code == 200 and full.content == CONTENT
    assert full.headers["content-type"] == "video/mp4" and full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(CONTENT))
    assert full.headers["cache-control"] == "private, no-store"
    part = client.get(f"/edits/{edit_id}/content", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == CONTENT[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(CONTENT)}"
    suffix = client.get(f"/edits/{edit_id}/content", headers={"Range": "bytes=-10"})
    assert suffix.status_code == 206 and suffix.content == CONTENT[-10:]
    bad = client.get(f"/edits/{edit_id}/content", headers={"Range": "bytes=99999-"})
    assert bad.status_code == 416 and bad.headers["content-range"] == f"bytes */{len(CONTENT)}"


def test_download_is_an_attachment_with_a_safe_vertical_name(client, db_session, storage):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    mark_ready(db_session, storage, edit_id)
    response = client.get(f"/edits/{edit_id}/download")
    assert response.status_code == 200 and response.content == CONTENT
    expected = f"that-was-crazy-vertical-{edit_id[:8]}.mp4"
    assert (
        response.headers["content-disposition"]
        == f"attachment; filename=\"{expected}\"; filename*=UTF-8''{expected}"
    )


def test_media_is_404_until_ready_and_for_unknown_ids(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    edit_id = client.post(ctx["base"], json=BLUR_BOLD).json()["id"]
    assert client.get(f"/edits/{edit_id}/content").status_code == 404
    assert client.get(f"/edits/{uuid.uuid4()}/download").status_code == 404
    assert client.get("/edits/not-a-uuid/content").status_code == 422
