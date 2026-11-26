"""TikTok for creators: connecting, what they may choose, and publishing a Short to it —
on the simulated provider (no network, no credentials)."""

import io
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import publish_jobs as jobs_api
from app.api import publishing_tiktok as api
from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.main import app
from app.models import ConnectionStatus, PublishingProvider, PublishJob, PublishStatus
from app.services.publishing import connections, pipeline, tiktok_post
from app.services.publishing.factory import get_publishing_provider
from app.services.publishing.metadata import MetadataError
from app.services.publishing.tiktok import CreatorInfo
from app.services.publishing.tiktok_oauth import Grant
from app.services.publishing.youtube_oauth import OAuthError
from app.services.storage import LocalStorageProvider
from tests.publishing_fixtures import CIPHER, KEY, connect, ready_edit

DATA = b"x" * 4096
REDIRECT = "https://api.example.test/publishing/tiktok/callback"
CHOICES = {"privacy_level": "FOLLOWER_OF_CREATOR", "allow_comment": True,
           "music_usage_confirmed": True}  # fmt: skip
BODY = {"title": "ignored for TikTok", "description": "How I priced my first course #creator",
        "platform": "tiktok", "options": CHOICES}  # fmt: skip


def configured(**overrides) -> Settings:
    base = {
        "publishing_token_encryption_key": KEY,
        "publishing_provider": "fake",
        "tiktok_publishing_enabled": True,
        "tiktok_client_key": "client-key",
        "tiktok_client_secret": "client-secret",
        "tiktok_oauth_redirect_uri": REDIRECT,
    }
    return Settings(**{**get_settings().model_dump(), **base, **overrides})


@pytest.fixture
def settings(monkeypatch) -> Settings:
    value = configured()
    for module in (api, jobs_api):
        monkeypatch.setattr(module, "get_settings", lambda: value)
    return value


@pytest.fixture
def storage(tmp_path):
    local = LocalStorageProvider(tmp_path / "media")
    app.dependency_overrides[get_storage] = lambda: local
    yield local
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def queue(monkeypatch):
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(
        jobs_api, "enqueue_publish", lambda job_id, *, task_id: queued.append(job_id)
    )
    return queued


def sign_in(client: TestClient, user_id) -> None:
    client.cookies.clear()
    client.cookies.set(get_settings().auth_cookie_name, create_access_token(user_id))


def connect_tiktok(db: Session, user, token: str = "tiktok-refresh"):
    return connections.save_connection(
        db, CIPHER, user_id=user.id, refresh_token=token, account_id="open-id-1",
        account_title="", scopes=["video.publish"], provider=PublishingProvider.TIKTOK,
    )  # fmt: skip


@pytest.fixture
def world(client: TestClient, db_session: Session, storage, settings, queue):
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(DATA), edit.storage_key)
    connection = connect_tiktok(db_session, user)
    sign_in(client, user.id)
    return {"user": user, "edit": edit, "connection": connection,
            "panel": f"/edits/{edit.id}/publish"}  # fmt: skip


def info(**overrides) -> CreatorInfo:
    base = {
        "nickname": "Amine",
        "username": "amine",
        "comment_disabled": False,
        "duet_disabled": False,
        "stitch_disabled": True,
        "max_duration_seconds": 600,
        "privacy_levels": ("PUBLIC_TO_EVERYONE", "FOLLOWER_OF_CREATOR", "SELF_ONLY"),
    }
    return CreatorInfo(**{**base, **overrides})


# --- the creator's choices ----------------------------------------------------------------


def test_choices_are_stored_as_chosen_and_nothing_is_defaulted_on():
    assert tiktok_post.choices(CHOICES, info(), 20.0) == {
        "privacy_level": "FOLLOWER_OF_CREATOR", "allow_comment": True, "allow_duet": False,
        "allow_stitch": False, "brand_organic": False, "brand_content": False,
        "music_usage_confirmed": True,
    }  # fmt: skip


@pytest.mark.parametrize(
    ("change", "field", "words"),
    [
        ({"privacy_level": None}, "privacy_level", "Choose who can see"),
        ({"privacy_level": "MUTUAL_FOLLOW_FRIENDS"}, "privacy_level", "not available"),
        ({"privacy_level": "EVERYONE"}, "privacy_level", "not available"),
        ({"allow_stitch": True}, "allow_stitch", "turned off in your TikTok settings"),
        ({"allow_duet": "yes"}, "allow_duet", "yes or no"),
        ({"commercial": True}, "commercial", "your brand, branded content or both"),
        ({"privacy_level": "SELF_ONLY", "commercial": True, "brand_content": True},
         "privacy_level", "cannot be visible only to you"),
        ({"music_usage_confirmed": False}, "music_usage_confirmed", "music usage"),
    ],
)  # fmt: skip
def test_choices_tiktok_does_not_allow_are_refused_with_their_field(change, field, words):
    with pytest.raises(MetadataError) as error:
        tiktok_post.choices({**CHOICES, **change}, info(), 20.0)
    assert error.value.field == field and words in error.value.message


def test_a_commercial_post_and_the_duration_limit():
    chosen = tiktok_post.choices(
        {**CHOICES, "commercial": True, "brand_organic": True, "brand_content": True}, info(), 20.0
    )
    assert chosen["brand_organic"] and chosen["brand_content"] and "commercial" not in chosen
    with pytest.raises(MetadataError) as error:
        tiktok_post.choices(CHOICES, info(max_duration_seconds=15), 20.0)
    assert error.value.field == "duration" and "15 seconds" in error.value.message
    assert tiktok_post.choices(CHOICES, info(max_duration_seconds=None), 9000.0)


def test_the_caption_is_checked_and_the_label_is_the_shorts_own_title():
    stored = tiktok_post.metadata("  My   Short  ", "  A caption #tag \n", "SELF_ONLY")
    assert (stored.title, stored.description, stored.privacy.value) == (
        "My Short", "A caption #tag", "private",
    )  # fmt: skip
    assert tiktok_post.metadata("t", "", "PUBLIC_TO_EVERYONE").privacy.value == "public"
    assert tiktok_post.metadata("t", "", "MUTUAL_FOLLOW_FRIENDS").privacy.value == "friends"
    for text in ("x" * 2201, "bad\x00char"):
        with pytest.raises(MetadataError) as error:
            tiktok_post.metadata("t", text, "SELF_ONLY")
        assert error.value.field == "description"


# --- connecting ---------------------------------------------------------------------------


def test_status_and_connect_follow_the_server_switch(client, db_session, monkeypatch, storage):
    assert client.get("/publishing/tiktok").status_code == 401
    user, _ = ready_edit(db_session)
    sign_in(client, user.id)

    off = configured(tiktok_publishing_enabled=False)
    monkeypatch.setattr(api, "get_settings", lambda: off)
    assert client.get("/publishing/tiktok").json() == {"enabled": False, "connection": None}
    assert client.post("/publishing/tiktok/connect").status_code == 409
    assert client.get("/publishing/tiktok/creator").status_code == 409

    on = configured()
    monkeypatch.setattr(api, "get_settings", lambda: on)
    url = client.post("/publishing/tiktok/connect").json()["authorization_url"]
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")
    assert query["scope"] == ["video.publish"] and query["redirect_uri"] == [REDIRECT]
    assert "client-secret" not in url


def test_the_callback_stores_the_connection_and_returns_to_settings(
    client, db_session, settings, monkeypatch
):
    user, _ = ready_edit(db_session)
    sign_in(client, user.id)
    state = parse_qs(
        urlsplit(client.post("/publishing/tiktok/connect").json()["authorization_url"]).query
    )["state"][0]
    monkeypatch.setattr(
        api.oauth, "exchange_code",
        lambda s, code: Grant("fresh-refresh", ["video.publish"], "open-id-9", "first-access"),
    )  # fmt: skip

    response = client.get(
        "/publishing/tiktok/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/settings?tiktok=connected")
    assert "fresh-refresh" not in response.headers["location"]
    connection = connections.get_connection(db_session, user.id, "tiktok")
    assert connection.account_id == "open-id-9" and connection.account_title == "@simulated"
    assert connections.refresh_token_of(db_session, CIPHER, connection) == "fresh-refresh"
    assert b"fresh-refresh" not in connection.refresh_token_ciphertext
    status = client.get("/publishing/tiktok").json()
    assert status["connection"]["provider"] == "tiktok" and "scopes" not in str(status)

    # The state was single use.
    again = client.get(
        "/publishing/tiktok/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert again.headers["location"].endswith("tiktok=error&reason=invalid_state")


@pytest.mark.parametrize(
    ("params", "reason"),
    [
        ({"state": "wrong", "code": "c"}, "invalid_state"),
        ({"code": "c"}, "invalid_state"),
        ({"state": "{state}", "error": "access_denied"}, "denied"),
        ({"state": "{state}", "code": "refused"}, "exchange_failed"),
    ],
)
def test_a_callback_that_does_not_complete_changes_nothing(
    client, db_session, settings, monkeypatch, params, reason
):
    user, _ = ready_edit(db_session)
    sign_in(client, user.id)
    state = parse_qs(
        urlsplit(client.post("/publishing/tiktok/connect").json()["authorization_url"]).query
    )["state"][0]

    def refuse(s, code):
        raise OAuthError("exchange_failed")

    monkeypatch.setattr(api.oauth, "exchange_code", refuse)
    sent = {k: v.replace("{state}", state) for k, v in params.items()}

    response = client.get("/publishing/tiktok/callback", params=sent, follow_redirects=False)

    assert response.headers["location"].endswith(f"/settings?tiktok=error&reason={reason}")
    assert connections.get_connection(db_session, user.id, "tiktok") is None


def test_the_callback_needs_the_signed_in_user(client, settings):
    client.cookies.clear()
    response = client.get(
        "/publishing/tiktok/callback", params={"state": "s", "code": "c"}, follow_redirects=False
    )
    assert response.headers["location"].endswith("tiktok=error&reason=signin_required")


def test_disconnecting_removes_only_tiktok(client, db_session, world):
    connect(db_session, world["user"])  # the creator also has YouTube

    assert client.delete("/publishing/tiktok").status_code == 200
    assert client.delete("/publishing/tiktok").status_code == 404
    assert set(connections.list_connections(db_session, world["user"].id)) == {"youtube"}


# --- what the creator may choose ------------------------------------------------------


def test_the_creator_endpoint_reports_what_tiktok_offers(client, db_session, world):
    body = client.get("/publishing/tiktok/creator").json()

    assert body == {
        "nickname": "Simulated creator", "username": "simulated",
        "privacy_levels": ["PUBLIC_TO_EVERYONE", "FOLLOWER_OF_CREATOR", "SELF_ONLY"],
        "comment_disabled": False, "duet_disabled": False, "stitch_disabled": True,
        "max_duration_seconds": 600,
    }  # fmt: skip
    assert world["connection"].account_title == "@simulated"  # learnt for display


def test_the_creator_endpoint_needs_a_working_connection(client, db_session, world, settings):
    provider = get_publishing_provider(settings, "tiktok")
    provider.revoked_tokens.add("tiktok-refresh")  # TikTok no longer accepts the grant
    try:
        assert client.get("/publishing/tiktok/creator").status_code == 409
        assert world["connection"].status == ConnectionStatus.NEEDS_RECONNECT
        assert client.get("/publishing/tiktok/creator").status_code == 409  # without asking again
    finally:
        provider.revoked_tokens.discard("tiktok-refresh")
    db_session.delete(world["connection"])
    db_session.commit()
    assert client.get("/publishing/tiktok/creator").status_code == 404


# --- publishing ---------------------------------------------------------------------------


def test_publishing_to_tiktok_creates_a_job_with_the_creators_choices(
    client, db_session, world, queue
):
    response = client.post(world["panel"], json=BODY)

    assert response.status_code == 201, response.text
    job = response.json()
    assert job["provider"] == "tiktok" and job["status"] == "queued"
    assert job["privacy"] == "followers" and job["video_url"] is None
    assert job["description"] == "How I priced my first course #creator"
    assert job["title"] == world["edit"].clip.candidate.title  # the Short's own title
    assert job["options"] == {
        "privacy_level": "FOLLOWER_OF_CREATOR", "allow_comment": True, "allow_duet": False,
        "allow_stitch": False, "brand_organic": False, "brand_content": False,
        "music_usage_confirmed": True,
    }  # fmt: skip
    assert queue == [uuid.UUID(job["id"])]

    again = client.post(world["panel"], json=BODY)
    assert again.status_code == 200 and again.json()["id"] == job["id"] and len(queue) == 1
    other = client.post(world["panel"], json={**BODY, "options": {**CHOICES, "allow_duet": True}})
    assert other.status_code == 201 and other.json()["id"] != job["id"]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"options": {**CHOICES, "privacy_level": None}}, "privacy_level"),
        ({"options": {**CHOICES, "privacy_level": "MUTUAL_FOLLOW_FRIENDS"}}, "privacy_level"),
        ({"options": {**CHOICES, "allow_stitch": True}}, "allow_stitch"),
        ({"options": {**CHOICES, "commercial": True}}, "commercial"),
        ({"options": {k: v for k, v in CHOICES.items() if k != "music_usage_confirmed"}},
         "music_usage_confirmed"),
        ({"description": "x" * 2201}, "description"),
    ],
)  # fmt: skip
def test_a_tiktok_post_that_breaks_a_rule_is_a_422_naming_the_field(
    client, db_session, world, queue, change, field
):
    response = client.post(world["panel"], json={**BODY, **change})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert db_session.scalar(select(PublishJob)) is None and queue == []


def test_publishing_to_tiktok_needs_the_server_switch_and_a_connection(
    client, db_session, world, monkeypatch
):
    assert client.post(world["panel"], json={**BODY, "platform": "myspace"}).status_code == 422

    world["connection"].status = ConnectionStatus.NEEDS_RECONNECT
    db_session.commit()
    assert "Reconnect your TikTok" in client.post(world["panel"], json=BODY).json()["detail"]
    db_session.delete(world["connection"])
    db_session.commit()
    assert "Connect a TikTok" in client.post(world["panel"], json=BODY).json()["detail"]

    off = configured(tiktok_publishing_enabled=False)
    monkeypatch.setattr(jobs_api, "get_settings", lambda: off)
    refused = client.post(world["panel"], json=BODY)
    assert refused.status_code == 409 and "TikTok publishing is not enabled" in refused.text


def test_each_platform_has_its_own_panel_and_its_own_waiting_post(
    client, db_session, world, monkeypatch, queue
):
    both = configured(
        youtube_publishing_enabled=True,
        google_client_id="x.apps.googleusercontent.com",
        google_client_secret="s",
        google_oauth_redirect_uri="http://localhost:8000/publishing/youtube/callback",
    )
    monkeypatch.setattr(jobs_api, "get_settings", lambda: both)
    connect(db_session, world["user"])
    when = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0).isoformat()

    on_tiktok = client.post(world["panel"], json={**BODY, "scheduled_at": when})
    on_youtube = client.post(world["panel"], json={"title": "On YouTube", "scheduled_at": when})

    assert on_tiktok.status_code == 201 and on_youtube.status_code == 201  # one per platform
    second = client.post(
        world["panel"],
        json={**BODY, "scheduled_at": when, "options": {**CHOICES, "allow_duet": True}},
    )
    assert second.status_code == 409 and "already scheduled" in second.json()["detail"]

    tiktok_panel = client.get(world["panel"], params={"platform": "tiktok"}).json()
    youtube_panel = client.get(world["panel"]).json()
    assert tiktok_panel["platform"] == "tiktok" and youtube_panel["platform"] == "youtube"
    assert [job["provider"] for job in tiktok_panel["jobs"]] == ["tiktok"]
    assert [job["provider"] for job in youtube_panel["jobs"]] == ["youtube"]
    assert tiktok_panel["connection"]["provider"] == "tiktok"
    assert client.get(world["panel"], params={"platform": "myspace"}).status_code == 422
    assert queue == []  # both wait for their time


def test_a_tiktok_job_runs_through_the_pipeline(client, db_session, world, storage, settings):
    job_id = uuid.UUID(client.post(world["panel"], json=BODY).json()["id"])
    job = db_session.get(PublishJob, job_id)

    pipeline.publish_short(job.id, db_session, settings=settings, storage=storage,
                           task_id=job.celery_task_id, sleep=lambda s: None)  # fmt: skip

    assert job.status == PublishStatus.UPLOADED, (job.error_code, job.error_message)
    read = client.get(f"/publish-jobs/{job.id}").json()
    assert read["simulated"] is True and read["video_url"] is None and read["studio_url"] is None
