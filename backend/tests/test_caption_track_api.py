"""The authenticated caption-timing API: ownership, idempotency, safe schemas, words, retry."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.api import caption_tracks as api
from app.api.caption_tracks import timing_available as real_timing_available
from app.core.config import Settings, get_settings
from app.models import CaptionTrack, CaptionTrackStatus, CaptionWord
from app.schemas.model_name import public_model_name
from app.services.storage import LocalStorageProvider
from app.workers.dispatch import JobQueueUnavailable
from tests.test_clip_edit_api import ready_clip, sign_up

TRACK_KEYS = {
    "id",
    "clip_id",
    "status",
    "progress_percent",
    "attempt",
    "is_stale",
    "timing_mode",
    "provider",
    "model",
    "language",
    "word_count",
    "rejected_word_count",
    "average_confidence",
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

    def fake_enqueue(track_id, *, task_id):
        row = db_session.get(CaptionTrack, track_id)
        assert row is not None and row.celery_task_id == task_id
        queued.append((track_id, task_id))
        return task_id

    monkeypatch.setattr(api, "enqueue_caption_track", fake_enqueue)
    monkeypatch.setattr(api, "timing_available", lambda settings: True)
    return queued


def clip_with_file(
    db: Session, storage: LocalStorageProvider, email="owner@example.com", **kwargs
) -> dict:
    ctx = ready_clip(db, email, **kwargs)
    path = storage.path_for(ctx["clip"].storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"clip bytes")
    ctx["clip_base"] = ctx["base"].removesuffix("/edits")
    ctx["base"] = ctx["clip_base"] + "/caption-tracks"
    return ctx


def complete(db: Session, track_id: str, words=("Hello", "there", "friend.")) -> CaptionTrack:
    track = db.get(CaptionTrack, uuid.UUID(track_id))
    track.status, track.progress_percent = CaptionTrackStatus.COMPLETED, 100
    track.language, track.word_count, track.rejected_word_count = "en", len(words), 0
    for i in reversed(range(len(words))):
        db.add(
            CaptionWord(
                track=track,
                sequence_index=i,
                start_time=i * 0.5,
                end_time=i * 0.5 + 0.4,
                text=words[i],
                confidence=0.9,
            )
        )
    db.commit()
    return track


# --- authentication and ownership -----


def _routes(ctx, track_id):
    return [
        ("post", ctx["base"]),
        ("get", ctx["base"]),
        ("get", f"{ctx['base']}/current"),
        ("get", f"{ctx['base']}/{track_id}"),
        ("get", f"{ctx['base']}/{track_id}/words"),
        ("post", f"{ctx['base']}/{track_id}/retry"),
        ("get", f"{ctx['clip_base']}/caption-timing"),
    ]


def test_anonymous_requests_are_401(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    client.post("/auth/logout")
    for method, url in _routes(ctx, track_id):
        assert getattr(client, method)(url).status_code == 401, url


def test_other_user_gets_404_everywhere(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    complete(db_session, track_id)
    client.post("/auth/logout")
    sign_up(client, "intruder@example.com")
    for method, url in _routes(ctx, track_id):
        assert getattr(client, method)(url).status_code == 404, url
    assert db_session.scalar(select(func.count()).select_from(CaptionTrack)) == 1


def test_a_track_of_another_clip_is_404_under_this_clip(client, db_session, storage):
    sign_up(client)
    first, second = clip_with_file(db_session, storage), clip_with_file(db_session, storage)
    track_id = client.post(first["base"]).json()["id"]
    complete(db_session, track_id)
    assert client.get(f"{second['base']}/{track_id}").status_code == 404
    assert client.get(f"{second['base']}/{track_id}/words").status_code == 404


# --- start -----


def test_start_queues_a_track_with_a_safe_schema(client, db_session, storage, fake_queue):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    response = client.post(ctx["base"], json={"provider": "../evil", "model": "/etc/passwd"})
    assert response.status_code == 201
    data = response.json()
    assert set(data) == TRACK_KEYS
    assert (
        data["status"] == "queued"
        and data["attempt"] == 1
        and data["timing_mode"] == "aligned_word"
    )
    assert (
        data["provider"] == "faster_whisper"
        and data["model"] == get_settings().faster_whisper_model
    )
    for forbidden in ("celery", "task", "fingerprint", "/etc", "evil", "config", str(storage.root)):
        assert forbidden not in response.text
    row = db_session.get(CaptionTrack, uuid.UUID(data["id"]))
    assert fake_queue == [(row.id, row.celery_task_id)]
    assert row.config["provider"] == "faster_whisper"  # server configuration, not the request


def test_the_transcript_language_becomes_the_hint(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    ctx["clip"].video.transcription.language = "fr"
    db_session.commit()
    row = db_session.get(CaptionTrack, uuid.UUID(client.post(ctx["base"]).json()["id"]))
    assert row.language_hint == "fr" and row.config["language_hint"] == "fr"


def test_repeated_start_returns_the_same_track(client, db_session, storage, fake_queue):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    first = client.post(ctx["base"])
    second = client.post(ctx["base"])
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"] and len(fake_queue) == 1


def test_a_failed_track_must_be_retried_explicitly(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    db_session.get(CaptionTrack, uuid.UUID(track_id)).status = CaptionTrackStatus.FAILED
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


def test_unavailable_timing_is_refused_up_front(client, db_session, storage, monkeypatch):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    monkeypatch.setattr(api, "timing_available", lambda settings: False)
    response = client.post(ctx["base"])
    assert (
        response.status_code == 409
        and response.json()["detail"] == "Word timing is not available on this server"
    )
    assert db_session.scalar(select(func.count()).select_from(CaptionTrack)) == 0


def test_queue_down_on_start_leaves_no_row(client, db_session, storage, monkeypatch):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)

    def down(track_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_caption_track", down)
    assert client.post(ctx["base"]).status_code == 503
    assert db_session.scalar(select(func.count()).select_from(CaptionTrack)) == 0


# --- read -----


def test_current_list_status_and_timing_options(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    options = client.get(f"{ctx['clip_base']}/caption-timing").json()
    assert options == {"word_timing": "none", "track": None, "phrase_timing_available": True}
    assert client.get(f"{ctx['base']}/current").status_code == 404
    track_id = client.post(ctx["base"]).json()["id"]
    assert client.get(f"{ctx['base']}/current").json()["id"] == track_id
    assert client.get(f"{ctx['base']}/{track_id}").json()["status"] == "queued"
    assert client.get(f"{ctx['clip_base']}/caption-timing").json()["word_timing"] == "running"
    page = client.get(ctx["base"]).json()
    assert page["total"] == 1 and [t["id"] for t in page["tracks"]] == [track_id]
    complete(db_session, track_id)
    options = client.get(f"{ctx['clip_base']}/caption-timing").json()
    assert options["word_timing"] == "completed" and options["track"]["word_count"] == 3


def test_phrase_timing_needs_a_completed_transcript(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage, transcript=False)
    assert (
        client.get(f"{ctx['clip_base']}/caption-timing").json()["phrase_timing_available"] is False
    )


def test_words_are_only_served_when_completed_and_in_order(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    assert client.get(f"{ctx['base']}/{track_id}/words").status_code == 409
    complete(db_session, track_id, words=("C'était", "مرحبا", "🔥"))
    data = client.get(f"{ctx['base']}/{track_id}/words").json()
    assert set(data) == {"track_id", "timing_mode", "language", "words"}
    assert data["timing_mode"] == "aligned_word" and data["language"] == "en"
    assert [w["text"] for w in data["words"]] == ["C'était", "مرحبا", "🔥"]
    assert [w["i"] for w in data["words"]] == [0, 1, 2]
    assert data["words"][1] == {
        "i": 1,
        "start": 0.5,
        "end": 0.9,
        "text": "مرحبا",
        "confidence": 0.9,
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
    track_id = client.post(ctx["base"]).json()["id"]
    assert client.post(f"{ctx['base']}/{track_id}/retry").status_code == 409  # queued
    complete(db_session, track_id)
    assert client.post(f"{ctx['base']}/{track_id}/retry").status_code == 409  # completed
    row = db_session.get(CaptionTrack, uuid.UUID(track_id))
    old_token = row.celery_task_id
    row.status, row.error_code, row.error_message = (
        CaptionTrackStatus.FAILED,
        "provider_failure",
        "x",
    )
    db_session.commit()
    data = client.post(f"{ctx['base']}/{track_id}/retry").json()
    assert data["status"] == "queued" and data["attempt"] == 2 and data["error_code"] is None
    db_session.refresh(row)
    assert row.celery_task_id != old_token and fake_queue[-1] == (row.id, row.celery_task_id)
    assert db_session.scalar(select(func.count()).select_from(CaptionWord)) == 0


def test_stalled_track_can_be_retried(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    row = db_session.get(CaptionTrack, uuid.UUID(track_id))
    row.status = CaptionTrackStatus.ALIGNING
    row.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=get_settings().caption_timing_stale_after_seconds + 5
    )
    db_session.commit()
    assert client.get(f"{ctx['base']}/{track_id}").json()["is_stale"] is True
    assert client.post(f"{ctx['base']}/{track_id}/retry").json()["attempt"] == 2


def test_retry_limit_and_row_lock(client, db_session, storage):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    row = db_session.get(CaptionTrack, uuid.UUID(track_id))
    row.status = CaptionTrackStatus.FAILED
    db_session.commit()
    statements = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        assert client.post(f"{ctx['base']}/{track_id}/retry").status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert any("FROM caption_tracks" in s and "FOR UPDATE" in s for s in statements)
    row.status, row.attempt = CaptionTrackStatus.FAILED, get_settings().caption_timing_max_attempts
    db_session.commit()
    response = client.post(f"{ctx['base']}/{track_id}/retry")
    assert response.status_code == 409 and "too many" in response.json()["detail"]


def test_retry_when_queue_is_down_marks_failed(client, db_session, storage, monkeypatch):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    db_session.get(CaptionTrack, uuid.UUID(track_id)).status = CaptionTrackStatus.FAILED
    db_session.commit()

    def down(track_id, *, task_id):
        raise JobQueueUnavailable("down")

    monkeypatch.setattr(api, "enqueue_caption_track", down)
    assert client.post(f"{ctx['base']}/{track_id}/retry").status_code == 503
    assert client.get(f"{ctx['base']}/{track_id}").json()["error_code"] == "queue_unavailable"


# --- availability (real check, nothing imported or loaded) -----


def test_timing_availability_checks_the_installed_package_without_importing_it():
    import sys

    before = "faster_whisper" in sys.modules
    assert real_timing_available(Settings(**get_settings().model_dump())) is True
    assert ("faster_whisper" in sys.modules) == before


# --- caption preview (the renderer's own layout, for the editor) -----


def test_caption_preview_returns_the_renderers_cues_lines_and_word_timing(
    client, db_session, storage, monkeypatch
):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    complete(db_session, track_id, words=("Nobody", "tells", "you."))
    url = f"{ctx['clip_base']}/caption-preview"
    data = client.get(url, params={"style": "focus", "track_id": track_id}).json()
    assert data["timing"] == "aligned_word" and data["emoji"] in ("monochrome", "omitted")
    (cue,) = data["cues"]
    assert cue["timed"] is True and [w["text"] for line in cue["lines"] for w in line] == [
        "Nobody",
        "tells",
        "you.",
    ]
    first = cue["lines"][0][0]
    assert (
        first["start"] == 0.0 and first["end"] == 0.5 and first["attached"] is False
    )  # active until "tells"
    phrase = client.get(url, params={"style": "punch", "timing": "phrase_fallback"}).json()
    assert phrase["timing"] == "phrase_fallback" and all(not c["timed"] for c in phrase["cues"])


def test_caption_preview_refuses_unusable_timing_and_respects_ownership(
    client, db_session, storage
):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    url = f"{ctx['clip_base']}/caption-preview"
    response = client.get(url, params={"style": "focus", "track_id": str(uuid.uuid4())})
    assert response.status_code == 409 and "word timing" in response.json()["detail"]
    assert client.get(url, params={"style": "sparkle"}).status_code == 422
    client.post("/auth/logout")
    assert client.get(url, params={"style": "focus"}).status_code == 401
    sign_up(client, "intruder@example.com")
    assert (
        client.get(url, params={"style": "focus", "timing": "phrase_fallback"}).status_code == 404
    )


def test_caption_preview_mirrors_the_emoji_policy(client, db_session, storage, monkeypatch):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    complete(db_session, track_id, words=("So", "🔥", "good"))
    monkeypatch.setattr(api, "emoji_font", lambda path: None)
    data = client.get(
        f"{ctx['clip_base']}/caption-preview", params={"style": "focus", "track_id": track_id}
    ).json()
    assert data["emoji"] == "omitted"
    assert [w["text"] for line in data["cues"][0]["lines"] for w in line] == ["So", "good"]


def test_a_local_model_directory_is_never_shown(client, db_session, storage, fake_queue):
    sign_up(client)
    ctx = clip_with_file(db_session, storage)
    track_id = client.post(ctx["base"]).json()["id"]
    row = db_session.get(CaptionTrack, uuid.UUID(track_id))
    row.model = "/srv/models/faster-whisper-small"
    db_session.commit()
    response = client.get(f"{ctx['base']}/{track_id}")
    assert response.json()["model"] == "custom" and "/srv" not in response.text


@pytest.mark.parametrize(
    ("configured", "shown"),
    [
        ("small", "small"),
        ("large-v3", "large-v3"),
        ("tiny.en", "tiny.en"),
        ("whisper-1", "whisper-1"),
        ("/srv/models/small", "custom"),
        ("models/small", "custom"),
        ("C:\\models\\small", "custom"),
        ("~/whisper", "custom"),
        ("..", "custom"),
    ],
)
def test_public_model_names(configured, shown):
    assert public_model_name(configured) == shown
