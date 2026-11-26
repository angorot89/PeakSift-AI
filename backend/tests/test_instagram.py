"""Instagram Reels through Facebook Login, against a mock of Meta's documented endpoints:
authorization, the single upload, publishing exactly once after processing, the creator API
and the whole pipeline. No network, no credentials."""

import io
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import publish_jobs as jobs_api
from app.api import publishing_instagram as api
from app.api.deps import get_storage
from app.core.config import Settings, get_settings, publishing_problems
from app.core.security import create_access_token
from app.main import app
from app.models import PublishingProvider, PublishJob, PublishStatus
from app.services.publishing import (
    connections,
    instagram,
    instagram_oauth,
    instagram_post,
    pipeline,
)
from app.services.publishing.instagram import InstagramProvider
from app.services.publishing.jobs import request_publish
from app.services.publishing.metadata import MetadataError, PublishMetadata
from app.services.publishing.provider import (
    PublishErrorCode,
    PublishProviderError,
    UploadState,
    VideoRequest,
)
from app.services.publishing.uploader import UploadSource, run_upload
from app.services.publishing.youtube_oauth import OAuthError
from app.services.storage import LocalStorageProvider
from tests.instagram_mock import IG_ID, REDIRECT, MockMeta, graph_error
from tests.publishing_fixtures import CIPHER, KEY, new_user, ready_edit

SEALED = instagram_oauth.seal("page-token-1", IG_ID)


def settings(**overrides) -> Settings:
    base = {
        "publishing_token_encryption_key": KEY,
        "instagram_publishing_enabled": True,
        "meta_app_id": "1234567890",
        "meta_app_secret": "app-secret",
        "instagram_oauth_redirect_uri": REDIRECT,
    }
    return Settings(**{**get_settings().model_dump(), **base, **overrides})


@pytest.fixture
def mock() -> MockMeta:
    return MockMeta()


@pytest.fixture
def provider(mock) -> InstagramProvider:
    return InstagramProvider(client=mock.client())


def request(size: int, caption: str = "How I priced my first course #creator") -> VideoRequest:
    return VideoRequest(title="Pricing", description=caption, tags=(), privacy="public",
                        made_for_kids=False, category_id="22", size_bytes=size)  # fmt: skip


def upload(provider, auth, session, data: bytes):
    seen: list[int] = []
    result = run_upload(
        provider, auth, session, UploadSource(len(data), lambda o, n: data[o : o + n]),
        chunk_bytes=256 * 1024, on_progress=seen.append, still_owner=lambda: None,
        sleep=lambda s: None,
    )  # fmt: skip
    return result, seen


# --- authorization --------------------------------------------------------------------


def test_the_consent_url_asks_for_publishing_permissions(db_session: Session):
    user = new_user(db_session)

    url = instagram_oauth.start(db_session, settings(), CIPHER, user.id)

    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}"
        == "https://www.facebook.com/v27.0/dialog/oauth"
    )
    assert query["client_id"] == "1234567890" and query["redirect_uri"] == REDIRECT
    assert query["response_type"] == "code"
    assert set(query["scope"].split(",")) == set(instagram_oauth.PERMISSIONS)
    assert "instagram_content_publish" in instagram_oauth.PERMISSIONS
    assert "app-secret" not in url


def test_a_state_is_single_use_and_bound_to_instagram(db_session: Session):
    from app.services.publishing import tiktok_oauth

    user = new_user(db_session)
    state = parse_qs(
        urlsplit(instagram_oauth.start(db_session, settings(), CIPHER, user.id)).query
    )["state"][0]
    with pytest.raises(OAuthError):  # TikTok's callback cannot use it
        tiktok_oauth.consume_state(db_session, state, user.id)
    state = parse_qs(
        urlsplit(instagram_oauth.start(db_session, settings(), CIPHER, user.id)).query
    )["state"][0]
    instagram_oauth.consume_state(db_session, state, user.id)
    with pytest.raises(OAuthError):  # single use
        instagram_oauth.consume_state(db_session, state, user.id)


def test_exchanging_the_code_keeps_the_page_token_of_the_instagram_account(mock):
    grant = instagram_oauth.exchange_code(settings(), "good-code", mock.client())

    assert instagram_oauth.unseal(grant.refresh_token) == ("page-token-1", IG_ID)
    assert (grant.account_id, grant.username) == (IG_ID, "amine.clips")
    assert "instagram_content_publish" in grant.scopes
    assert "page-token-1" not in repr(grant)
    # The long-lived exchange happened, and tokens went in headers, never in a URL.
    exchange = [r for r in mock.requests if r.url.params.get("grant_type") == "fb_exchange_token"]
    assert len(exchange) == 1
    accounts = mock.calls("GET", "/me/accounts")[0]
    assert "long-user-token" not in str(accounts.url)
    assert accounts.headers["Authorization"] == "OAuth long-user-token"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("used_code", "exchange_failed"),
        ("no_publish_permission", "insufficient_scope"),
        ("no_instagram_account", "no_instagram_account"),
        ("declined", "denied"),
    ],
)
def test_a_connection_that_cannot_publish_is_not_saved(mock, change, code):
    sent = "good-code"
    if change == "used_code":
        mock.codes.clear()
    elif change == "no_publish_permission":
        mock.granted.remove("instagram_content_publish")
    elif change == "no_instagram_account":
        mock.pages = mock.pages[:1]
    else:
        sent = ""
    with pytest.raises(OAuthError) as error:
        instagram_oauth.exchange_code(settings(), sent, mock.client())
    assert error.value.code == code


def test_revoking_is_never_claimed():
    with pytest.raises(OAuthError):
        instagram_oauth.revoke(SEALED)


def test_a_stored_value_that_is_not_ours_needs_reconnecting(provider):
    for bad in ("", "token", '{"t": "x"}', '{"t": "x", "ig": "not-a-number"}'):
        with pytest.raises(PublishProviderError) as error:
            provider.authorize(bad)
        assert error.value.code == PublishErrorCode.AUTHENTICATION_REQUIRED
        assert error.value.message.startswith("Instagram needs you to reconnect")
    auth = provider.authorize(SEALED)
    assert (auth.access_token, auth.account_id) == ("page-token-1", IG_ID)


# --- the post ---------------------------------------------------------------------------


def test_a_reel_is_uploaded_whole_then_published_once_after_processing(provider, mock):
    data = b"\x11" * 70_000
    auth = provider.authorize(SEALED)
    session = provider.start_upload(auth, request(len(data)))
    container = instagram.Session.load(session).container_id

    result, seen = upload(provider, auth, session, data)

    assert result.complete and result.video_id == container and seen[-1] == len(data)
    assert mock.containers[container]["bytes"] == data
    assert mock.containers[container]["caption"] == "How I priced my first course #creator"
    post = mock.calls("POST", f"/{container}")[0]
    assert (post.headers["offset"], post.headers["file_size"]) == ("0", str(len(data)))
    assert post.headers["Authorization"] == "OAuth page-token-1"
    assert mock.published == []  # nothing is on Instagram yet

    assert provider.video_status(auth, container).upload == UploadState.UPLOADED  # processing
    assert provider.video_status(auth, container).upload == UploadState.PROCESSED  # published now
    assert provider.video_status(auth, container).upload == UploadState.PROCESSED  # not again
    assert mock.published == [container]


def test_a_second_check_never_publishes_twice(provider, mock):
    auth = provider.authorize(SEALED)
    session = provider.start_upload(auth, request(10))
    container = instagram.Session.load(session).container_id
    upload(provider, auth, session, b"0123456789")
    mock.containers[container]["status"] = "FINISHED"
    # Another check published it between this check's two requests.
    mock.next_responses.extend([
        httpx.Response(200, json={"status_code": "FINISHED"}),
        graph_error(400, 9007),
        httpx.Response(200, json={"status_code": "PUBLISHED"}),
    ])  # fmt: skip

    assert provider.video_status(auth, container).upload == UploadState.PROCESSED
    assert mock.published == []  # this check did not publish it


@pytest.mark.parametrize(
    ("caption", "words"),
    [("x" * 2201, "2200"), ("#a " * 31, "30 hashtags"), ("@a " * 21, "20 mentions")],
)
def test_a_caption_instagram_would_refuse_is_refused_not_cut(provider, mock, caption, words):
    auth = provider.authorize(SEALED)
    with pytest.raises(PublishProviderError) as error:
        provider.start_upload(auth, request(10, caption))
    assert error.value.code == PublishErrorCode.INVALID_METADATA and words in error.value.message
    assert mock.calls("POST", "/media") == []


def test_a_reel_over_300_mb_is_refused(provider, mock):
    with pytest.raises(PublishProviderError) as error:
        provider.start_upload(provider.authorize(SEALED), request(300 * 1024 * 1024 + 1))
    assert "300 MB" in error.value.message and mock.calls("POST", "/media") == []


def test_after_an_interruption_the_whole_file_goes_again(provider, mock):
    data = b"\x12" * 5000
    auth = provider.authorize(SEALED)
    session = provider.start_upload(auth, request(len(data)))
    mock.next_responses.append(httpx.Response(503, json={"debug_info": {"retriable": True}}))

    result, _ = upload(provider, auth, session, data)

    container = instagram.Session.load(session).container_id
    assert result.complete and mock.containers[container]["bytes"] == data
    assert len(mock.calls("POST", "/media")) == 1  # the same container, no second post


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (graph_error(401, 190), PublishErrorCode.AUTHENTICATION_REQUIRED),
        (graph_error(403, 10), PublishErrorCode.PERMISSION_DENIED),
        (graph_error(400, 4), PublishErrorCode.RATE_LIMITED),
        (graph_error(400, 9), PublishErrorCode.QUOTA_EXCEEDED),
        (graph_error(400, 100), PublishErrorCode.INVALID_METADATA),
        (graph_error(500, 2, transient=True), PublishErrorCode.PROVIDER_ERROR),
        (httpx.Response(200, text="<html>"), PublishErrorCode.PROVIDER_ERROR),
    ],
)
def test_metas_refusals_become_plain_reasons(provider, mock, response, code):
    mock.next_responses.append(response)
    with pytest.raises(PublishProviderError) as error:
        provider.start_upload(provider.authorize(SEALED), request(10))
    assert error.value.code == code and error.value.message.startswith(
        ("Instagram", "This Instagram", "The upload")
    )
    assert "Meta says no" not in error.value.message and "trace-1" not in error.value.message


@pytest.mark.parametrize(("state", "reason"), [("ERROR", "2207026"), ("EXPIRED", "expired")])
def test_a_container_meta_could_not_use_fails_with_its_reason(provider, mock, state, reason):
    auth = provider.authorize(SEALED)
    session = provider.start_upload(auth, request(10))
    container = instagram.Session.load(session).container_id
    mock.next_responses.append(
        httpx.Response(
            200, json={"status_code": state, "status": "2207026" if state == "ERROR" else ""}
        )
    )
    status = provider.video_status(auth, container)
    assert (status.upload, status.reason) == (UploadState.FAILED, reason)
    assert mock.published == []


# --- the post as the creator reviewed it --------------------------------------------------


def test_the_stored_post_is_public_with_the_creators_caption():
    stored = instagram_post.metadata("  My   Short ", "  A caption #tag  ", 30.0)
    assert (stored.title, stored.description, stored.privacy.value) == (
        "My Short", "A caption #tag", "public",
    )  # fmt: skip
    cases = (
        ("x" * 2201, 30.0, "description"),
        ("ok", 2.0, "duration"),
        ("ok", 901.0, "duration"),
        ("bad\x00", 30.0, "description"),
    )
    for caption, duration, field in cases:
        with pytest.raises(MetadataError) as error:
            instagram_post.metadata("t", caption, duration)
        assert error.value.field == field


# --- the whole pipeline -------------------------------------------------------------------


def test_the_pipeline_posts_a_reel_and_says_published_only_after_publishing(
    db_session: Session, tmp_path, mock, provider
):
    data = b"\x13" * 9000
    storage = LocalStorageProvider(tmp_path / "media")
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(data), edit.storage_key)
    connection = connections.save_connection(
        db_session, CIPHER, user_id=user.id, refresh_token=SEALED, account_id=IG_ID,
        account_title="@amine.clips", scopes=["instagram_content_publish"],
        provider=PublishingProvider.INSTAGRAM,
    )  # fmt: skip
    job, _ = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connection, task_id="task-1",
        metadata=instagram_post.metadata("Pricing", "How I priced it", 20.0), platform="Instagram",
    )  # fmt: skip

    pipeline.publish_short(job.id, db_session, settings=settings(), storage=storage,
                           provider=provider, task_id="task-1", sleep=lambda s: None)  # fmt: skip
    assert job.status == PublishStatus.UPLOADED and mock.published == []

    pipeline.check_status(job.id, db_session, settings=settings(), provider=provider)
    assert job.status == PublishStatus.PROCESSING and mock.published == []
    pipeline.check_status(job.id, db_session, settings=settings(), provider=provider)
    assert job.status == PublishStatus.PUBLISHED and mock.published == [job.provider_video_id]


def test_a_reel_still_processing_when_checks_run_out_is_not_called_posted(
    db_session: Session, tmp_path, provider
):
    mock_slow = MockMeta(processing_polls=99)
    slow = InstagramProvider(client=mock_slow.client())
    storage = LocalStorageProvider(tmp_path / "media")
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(b"\x14" * 100), edit.storage_key)
    connection = connections.save_connection(
        db_session, CIPHER, user_id=user.id, refresh_token=SEALED, account_id=IG_ID,
        account_title="", scopes=["instagram_content_publish"],
        provider=PublishingProvider.INSTAGRAM,
    )  # fmt: skip
    job, _ = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connection, task_id="task-1",
        metadata=PublishMetadata.create(title="Slow"), platform="Instagram",
    )  # fmt: skip
    limited = settings(publish_status_max_polls=2)
    pipeline.publish_short(job.id, db_session, settings=limited, storage=storage,
                           provider=slow, task_id="task-1", sleep=lambda s: None)  # fmt: skip

    for _ in range(3):
        pipeline.check_status(job.id, db_session, settings=limited, provider=slow)

    assert job.status == PublishStatus.PROVIDER_FAILED and mock_slow.published == []
    assert "was not posted" in job.error_message and "Instagram" in job.error_message


# --- the creator API (simulated provider) -------------------------------------------------


@pytest.fixture
def api_world(client: TestClient, db_session: Session, monkeypatch, tmp_path):
    value = settings(publishing_provider="fake")
    for module in (api, jobs_api):
        monkeypatch.setattr(module, "get_settings", lambda: value)
    local = LocalStorageProvider(tmp_path / "media")
    app.dependency_overrides[get_storage] = lambda: local
    queued: list = []
    monkeypatch.setattr(
        jobs_api, "enqueue_publish", lambda job_id, *, task_id: queued.append(job_id)
    )
    user, edit = ready_edit(db_session)
    local.save(io.BytesIO(b"x" * 4096), edit.storage_key)
    client.cookies.clear()
    client.cookies.set(get_settings().auth_cookie_name, create_access_token(user.id))
    yield {"user": user, "edit": edit, "queued": queued, "panel": f"/edits/{edit.id}/publish"}
    app.dependency_overrides.pop(get_storage, None)


def test_connecting_and_the_callback(client, db_session, api_world, monkeypatch):
    assert client.get("/publishing/instagram").json() == {"enabled": True, "connection": None}
    url = client.post("/publishing/instagram/connect").json()["authorization_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    grant = instagram_oauth.Grant(SEALED, ["instagram_content_publish"], IG_ID, "amine.clips")
    monkeypatch.setattr(api.oauth, "exchange_code", lambda s, code: grant)

    response = client.get("/publishing/instagram/callback", params={"state": state, "code": "c"},
                          follow_redirects=False)  # fmt: skip

    assert response.headers["location"].endswith("/settings?instagram=connected")
    connection = connections.get_connection(db_session, api_world["user"].id, "instagram")
    assert (connection.account_id, connection.account_title) == (IG_ID, "@amine.clips")
    assert connections.refresh_token_of(db_session, CIPHER, connection) == SEALED
    assert b"page-token-1" not in connection.refresh_token_ciphertext

    # Disconnecting removes it here; Meta's side is not claimed.
    assert client.delete("/publishing/instagram").json() == {"revoked_with_provider": False}
    assert connections.get_connection(db_session, api_world["user"].id, "instagram") is None


def test_a_callback_without_an_instagram_account_says_so(client, api_world, monkeypatch):
    url = client.post("/publishing/instagram/connect").json()["authorization_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]

    def none(s, code):
        raise OAuthError("no_instagram_account")

    monkeypatch.setattr(api.oauth, "exchange_code", none)
    response = client.get("/publishing/instagram/callback", params={"state": state, "code": "c"},
                          follow_redirects=False)  # fmt: skip
    assert response.headers["location"].endswith("instagram=error&reason=no_instagram_account")


def test_publishing_a_reel_through_the_api(client, db_session, api_world):
    connections.save_connection(
        db_session, CIPHER, user_id=api_world["user"].id, refresh_token=SEALED, account_id=IG_ID,
        account_title="@amine.clips", scopes=["instagram_content_publish"],
        provider=PublishingProvider.INSTAGRAM,
    )  # fmt: skip
    body = {"platform": "instagram", "title": "x", "description": "How I priced it #creator"}

    response = client.post(api_world["panel"], json=body)

    assert response.status_code == 201, response.text
    job = response.json()
    assert (job["provider"], job["privacy"], job["status"]) == ("instagram", "public", "queued")
    assert job["description"] == "How I priced it #creator" and job["video_url"] is None
    assert api_world["queued"] == [uuid.UUID(job["id"])]
    refused = client.post(api_world["panel"], json={**body, "description": "#a " * 31})
    assert refused.status_code == 422 and refused.json()["detail"][0]["loc"] == [
        "body",
        "description",
    ]
    panel = client.get(api_world["panel"], params={"platform": "instagram"}).json()
    assert panel["platform"] == "instagram" and [j["provider"] for j in panel["jobs"]] == [
        "instagram"
    ]


def test_publishing_to_instagram_needs_a_connection_and_the_switch(
    client, db_session, api_world, monkeypatch
):
    body = {"platform": "instagram", "title": "x", "description": "Hi"}
    assert "Connect an Instagram account" in client.post(api_world["panel"], json=body).text
    off = settings(instagram_publishing_enabled=False)
    monkeypatch.setattr(jobs_api, "get_settings", lambda: off)
    assert client.post(api_world["panel"], json=body).status_code == 409
    assert db_session.scalar(select(PublishJob)) is None


# --- configuration ------------------------------------------------------------------------


def test_instagram_settings_are_checked_only_when_switched_on():
    off = Settings(**{**get_settings().model_dump(), "instagram_publishing_enabled": False})
    assert not [p for p in publishing_problems(off) if "META" in p or "INSTAGRAM" in p]
    assert not [p for p in publishing_problems(settings()) if "META" in p or "INSTAGRAM" in p]
    with pytest.raises(ValidationError) as refused:
        settings(
            meta_app_id="abc",
            meta_app_secret="",
            instagram_oauth_redirect_uri="http://example.test/publishing/instagram/callback",
        )
    for name in ("META_APP_ID", "META_APP_SECRET", "INSTAGRAM_OAUTH_REDIRECT_URI"):
        assert name in str(refused.value)
