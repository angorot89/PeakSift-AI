"""TikTok behind the publishing contract, against a mock of TikTok's documented endpoints:
authorization, rotating refresh tokens, the declared chunk plan, resuming, the status mapping
and the whole pipeline. No network, no credentials."""

import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings, publishing_problems
from app.models import OAuthState, PublishingProvider, PublishStatus
from app.services.publishing import connections, pipeline, tiktok, tiktok_oauth
from app.services.publishing import youtube_oauth as google
from app.services.publishing.jobs import request_publish
from app.services.publishing.metadata import PublishMetadata, fingerprint
from app.services.publishing.provider import (
    PublishErrorCode,
    PublishProviderError,
    UploadState,
    VideoRequest,
)
from app.services.publishing.tiktok import TikTokProvider, chunk_plan
from app.services.publishing.tokens import TokenDecryptionError
from app.services.publishing.uploader import UploadSource, run_upload
from app.services.publishing.youtube_oauth import OAuthError
from app.services.storage import LocalStorageProvider
from tests.publishing_fixtures import CIPHER, KEY, new_user, ready_edit
from tests.tiktok_mock import INIT_URL, STATUS_URL, TOKEN_URL, MockTikTok, api_error, ok

MIB = 1024 * 1024
REDIRECT = "https://api.example.test/publishing/tiktok/callback"


def settings(**overrides) -> Settings:
    base = {
        "publishing_token_encryption_key": KEY,
        "tiktok_publishing_enabled": True,
        "tiktok_client_key": "client-key",
        "tiktok_client_secret": "client-secret",
        "tiktok_oauth_redirect_uri": REDIRECT,
        "tiktok_upload_chunk_bytes": 5 * MIB,
    }
    return Settings(**{**get_settings().model_dump(), **base, **overrides})


@pytest.fixture
def mock() -> MockTikTok:
    return MockTikTok()


@pytest.fixture
def provider(mock) -> TikTokProvider:
    return TikTokProvider("client-key", "client-secret", chunk_bytes=5 * MIB, client=mock.client())


def request(size: int, **options) -> VideoRequest:
    return VideoRequest(
        title="Pricing", description="How I priced my first course #creator", tags=(),
        privacy="private", made_for_kids=False, category_id="22", size_bytes=size,
        options={"privacy_level": "SELF_ONLY", **options},
    )  # fmt: skip


def upload(provider, auth, session, data: bytes, **kwargs):
    confirmed: list[int] = []
    result = run_upload(
        provider, auth, session, UploadSource(len(data), lambda o, n: data[o : o + n]),
        chunk_bytes=256 * 1024, on_progress=confirmed.append, still_owner=lambda: None,
        sleep=lambda s: None, **kwargs,
    )  # fmt: skip
    return result, confirmed


# --- the chunk plan -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "preferred", "expected"),
    [
        (1, 10 * MIB, (1, 1)),  # under 5 MB: one chunk, the whole file
        (5 * MIB - 1, 10 * MIB, (5 * MIB - 1, 1)),
        (5 * MIB, 10 * MIB, (10 * MIB, 1)),  # under one preferred chunk: still one request
        (12 * MIB, 5 * MIB, (5 * MIB, 2)),  # 5 + 7: the last chunk carries the remainder
        (50_000_123, 10_000_000, (10_000_000, 5)),  # TikTok's own documented example
        (20 * MIB, 1, (5 * MIB, 4)),  # a preferred size below TikTok's minimum is raised
        (4_000_000_000, 100_000_000, (64_000_000, 62)),  # … and one above its maximum lowered
    ],
)
def test_chunk_plan_follows_tiktoks_rules(size, preferred, expected):
    chunk, count = chunk_plan(size, preferred)
    assert (chunk, count) == expected
    assert count == max(1, size // chunk) and count <= 1000
    last = size - (count - 1) * chunk
    assert 0 < last < 2 * chunk and last <= 128_000_000


def test_an_empty_file_is_refused():
    with pytest.raises(PublishProviderError):
        chunk_plan(0, 5 * MIB)


# --- authorization --------------------------------------------------------------------


def test_authorizing_rotates_the_refresh_token(provider, mock):
    auth = provider.authorize("rt-0")

    assert auth.access_token == "at-1" and auth.rotated_refresh_token == "rt-1"
    assert "at-1" not in repr(auth) and "rt-1" not in repr(auth)
    form = parse_qs(mock.calls(TOKEN_URL)[0].content.decode())
    assert form["grant_type"] == ["refresh_token"] and form["client_key"] == ["client-key"]

    # The old token is dead: using it again is "reconnect", not a silent success.
    with pytest.raises(PublishProviderError) as dead:
        provider.authorize("rt-0")
    assert dead.value.code == PublishErrorCode.AUTHENTICATION_REQUIRED
    assert dead.value.message.startswith("TikTok needs you to reconnect")
    assert provider.authorize("rt-1").rotated_refresh_token == "rt-2"


def test_authorizing_when_tiktok_is_down_is_retryable(provider, mock):
    mock.next_responses.append(httpx.Response(503))
    with pytest.raises(PublishProviderError) as error:
        provider.authorize("rt-0")
    assert error.value.code == PublishErrorCode.PROVIDER_ERROR and error.value.retryable
    assert "rt-0" in mock.refresh_tokens  # nothing was consumed


def test_the_consent_url_asks_only_for_publishing(db_session: Session):
    user = new_user(db_session)

    url = tiktok_oauth.start(db_session, settings(), CIPHER, user.id)

    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}"
        == "https://www.tiktok.com/v2/auth/authorize/"
    )
    assert query["client_key"] == "client-key" and query["scope"] == "video.publish"
    assert query["response_type"] == "code" and query["redirect_uri"] == REDIRECT
    assert "client-secret" not in url
    row = db_session.scalar(select(OAuthState).where(OAuthState.user_id == user.id))
    assert row.provider == "tiktok" and query["state"] not in row.state_hash  # stored hashed
    assert len(row.state_hash) == 64


def test_a_state_is_single_use_user_bound_and_short_lived(db_session: Session):
    user, other = new_user(db_session), new_user(db_session)
    state = parse_qs(urlsplit(tiktok_oauth.start(db_session, settings(), CIPHER, user.id)).query)[
        "state"
    ][0]

    with pytest.raises(OAuthError):  # another user's browser
        tiktok_oauth.consume_state(db_session, state, other.id)
    with pytest.raises(OAuthError):  # … and it was consumed by that attempt: single use
        tiktok_oauth.consume_state(db_session, state, user.id)

    fresh = parse_qs(urlsplit(tiktok_oauth.start(db_session, settings(), CIPHER, user.id)).query)[
        "state"
    ][0]
    tiktok_oauth.consume_state(db_session, fresh, user.id)  # the right user, once

    expired = parse_qs(urlsplit(tiktok_oauth.start(db_session, settings(), CIPHER, user.id)).query)[
        "state"
    ][0]
    db_session.execute(
        OAuthState.__table__.update().values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db_session.commit()
    with pytest.raises(OAuthError) as late:
        tiktok_oauth.consume_state(db_session, expired, user.id)
    assert late.value.code == "expired"
    for bad in ("", "x" * 300):
        with pytest.raises(OAuthError):
            tiktok_oauth.consume_state(db_session, bad, user.id)


def test_states_do_not_cross_between_platforms(db_session: Session):
    user = new_user(db_session)
    state = parse_qs(urlsplit(tiktok_oauth.start(db_session, settings(), CIPHER, user.id)).query)[
        "state"
    ][0]
    # YouTube's callback cannot use a TikTok state …
    with pytest.raises((OAuthError, TokenDecryptionError)):
        google.consume_state(db_session, CIPHER, state, user.id)

    google_settings = Settings(
        **{**get_settings().model_dump(), "publishing_token_encryption_key": KEY,
           "google_client_id": "x.apps.googleusercontent.com", "google_client_secret": "s",
           "google_oauth_redirect_uri": "http://localhost:8000/publishing/youtube/callback"}
    )  # fmt: skip
    google_state = parse_qs(
        urlsplit(google.start(db_session, google_settings, CIPHER, user.id)).query
    )["state"][0]
    # … and TikTok's cannot use a YouTube one.
    with pytest.raises(OAuthError):
        tiktok_oauth.consume_state(db_session, google_state, user.id)


def test_exchanging_the_code(mock):
    grant = tiktok_oauth.exchange_code(settings(), "good-code", mock.client())

    assert grant.refresh_token == "rt-1" and grant.scopes == ["video.publish"]
    assert grant.open_id == "open-id-1" and "rt-1" not in repr(grant)
    form = parse_qs(mock.calls(TOKEN_URL)[0].content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["redirect_uri"] == [REDIRECT]

    for code, expected in (("good-code", "exchange_failed"), ("", "denied")):  # used; declined
        with pytest.raises(OAuthError) as refused:
            tiktok_oauth.exchange_code(settings(), code, mock.client())
        assert refused.value.code == expected


def test_a_grant_without_the_publish_scope_is_not_saved(mock):
    mock.codes["basic-only"] = "user.info.basic"
    with pytest.raises(OAuthError) as error:
        tiktok_oauth.exchange_code(settings(), "basic-only", mock.client())
    assert error.value.code == "insufficient_scope"


def test_revoking(mock):
    tiktok_oauth.revoke(settings(), "rt-0", mock.client())
    assert mock.revoked == ["rt-0"]
    mock.next_responses.append(httpx.Response(500))
    with pytest.raises(OAuthError):
        tiktok_oauth.revoke(settings(), "rt-0", mock.client())


# --- what the creator may choose ----------------------------------------------------------


def test_creator_info_reports_what_this_creator_may_choose(provider, mock):
    mock.privacy_levels = ["PUBLIC_TO_EVERYONE", "SELF_ONLY", "SOMETHING_NEW"]

    info = provider.creator_info(provider.authorize("rt-0"))

    assert (info.nickname, info.username) == ("Amine", "amine.clips")
    assert info.privacy_levels == ("PUBLIC_TO_EVERYONE", "SELF_ONLY")  # unknown levels dropped
    assert (info.comment_disabled, info.duet_disabled, info.stitch_disabled) == (False, True, False)
    assert info.max_duration_seconds == 600


# --- starting a post ----------------------------------------------------------------------


def test_starting_a_post_sends_what_the_creator_chose(provider, mock):
    auth = provider.authorize("rt-0")

    session = provider.start_upload(auth, request(12 * MIB, allow_comment=True, brand_organic=True))

    body = json.loads(mock.calls(INIT_URL)[0].content)
    assert body["post_info"] == {
        "title": "How I priced my first course #creator", "privacy_level": "SELF_ONLY",
        "disable_comment": False, "disable_duet": True, "disable_stitch": True,
        "brand_organic_toggle": True, "brand_content_toggle": False, "is_aigc": False,
    }  # fmt: skip
    assert body["source_info"] == {"source": "FILE_UPLOAD", "video_size": 12 * MIB,
                                   "chunk_size": 5 * MIB, "total_chunk_count": 2}  # fmt: skip
    stored = tiktok.Session.load(session)
    assert stored.publish_id in mock.publishes and stored.upload_url.startswith("https://")
    assert (stored.chunk_size, stored.chunks) == (5 * MIB, 2)


def test_visibility_is_never_defaulted(provider, mock):
    auth = provider.authorize("rt-0")
    for options in ({}, {"privacy_level": None}, {"privacy_level": "EVERYONE"}):
        bare = VideoRequest(title="t", description="", tags=(), privacy="private",
                            made_for_kids=False, category_id="22", size_bytes=MIB,
                            options=options)  # fmt: skip
        with pytest.raises(PublishProviderError) as error:
            provider.start_upload(auth, bare)
        assert error.value.code == PublishErrorCode.INVALID_METADATA
    assert mock.calls(INIT_URL) == []  # nothing was sent to TikTok


def test_a_caption_that_is_too_long_is_refused_not_cut(provider, mock):
    auth = provider.authorize("rt-0")
    long = VideoRequest(
        title="t",
        description="😀" * 1101,
        tags=(),
        privacy="private",
        made_for_kids=False,
        category_id="22",
        size_bytes=MIB,
        options={"privacy_level": "SELF_ONLY"},
    )  # fmt: skip  (2202 UTF-16 units)
    with pytest.raises(PublishProviderError) as error:
        provider.start_upload(auth, long)
    assert error.value.code == PublishErrorCode.INVALID_METADATA and "2200" in error.value.message
    assert mock.calls(INIT_URL) == []


@pytest.mark.parametrize(
    ("response", "code", "words"),
    [
        (api_error(403, "unaudited_client_can_only_post_to_private_accounts"),
         PublishErrorCode.PERMISSION_DENIED, "private"),
        (api_error(403, "reached_active_user_cap"), PublishErrorCode.PERMISSION_DENIED, "tomorrow"),
        (api_error(429, "rate_limit_exceeded"), PublishErrorCode.RATE_LIMITED, "slow down"),
        (api_error(403, "spam_risk_too_many_posts"), PublishErrorCode.QUOTA_EXCEEDED, "limit"),
        (api_error(401, "access_token_invalid"), PublishErrorCode.AUTHENTICATION_REQUIRED,
         "reconnect"),
        (api_error(403, "scope_not_authorized"), PublishErrorCode.PERMISSION_DENIED, "cannot"),
        (api_error(400, "privacy_level_option_mismatch"), PublishErrorCode.INVALID_METADATA,
         "visibility"),
        (api_error(500, "internal"), PublishErrorCode.PROVIDER_ERROR, "problem"),
        (httpx.Response(200, text="<html>"), PublishErrorCode.PROVIDER_ERROR, "problem"),
    ],
)  # fmt: skip
def test_tiktoks_refusals_become_plain_reasons(provider, mock, response, code, words):
    auth = provider.authorize("rt-0")
    mock.next_responses.append(response)

    with pytest.raises(PublishProviderError) as error:
        provider.start_upload(auth, request(MIB))

    assert error.value.code == code and words in error.value.message
    assert "TikTok says no" not in error.value.message and "log-1" not in error.value.message


def test_a_network_failure_is_retryable(mock):
    def unreachable(req):
        raise httpx.ConnectError("no route")

    client = httpx.Client(transport=httpx.MockTransport(unreachable))
    provider = TikTokProvider("client-key", "client-secret", client=client)
    with pytest.raises(PublishProviderError) as error:
        provider.authorize("rt-0")
    assert error.value.code == PublishErrorCode.NETWORK_ERROR and error.value.retryable


# --- uploading ----------------------------------------------------------------------------


def test_a_small_file_goes_as_one_request(provider, mock):
    data = bytes(range(256)) * 400  # 102 400 bytes
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))

    result, confirmed = upload(provider, auth, session, data)

    publish_id = tiktok.Session.load(session).publish_id
    assert result.complete and result.video_id == publish_id
    assert mock.publishes[publish_id]["bytes"] == data and confirmed == [0, len(data)]
    puts = [r for r in mock.requests if r.method == "PUT"]
    assert (
        len(puts) == 1
        and puts[0].headers["Content-Range"] == f"bytes 0-{len(data) - 1}/{len(data)}"
    )
    assert "Authorization" not in puts[0].headers  # the upload URL is its own credential


def test_a_large_file_follows_the_declared_plan(provider, mock):
    data = b"\x07" * (12 * MIB + 3)
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))

    result, confirmed = upload(provider, auth, session, data)

    assert result.complete and confirmed == [0, 5 * MIB, len(data)]
    ranges = [r.headers["Content-Range"] for r in mock.requests if r.method == "PUT"]
    assert ranges == [f"bytes 0-{5 * MIB - 1}/{len(data)}",
                      f"bytes {5 * MIB}-{len(data) - 1}/{len(data)}"]  # fmt: skip
    assert mock.publishes[tiktok.Session.load(session).publish_id]["bytes"] == data


def test_an_interrupted_upload_resumes_where_tiktok_says(provider, mock):
    data = b"\x09" * (16 * MIB)
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))
    publish_id = tiktok.Session.load(session).publish_id
    provider.upload_chunk(auth, session, data[: 5 * MIB], 0, len(data))  # then the worker died

    result, confirmed = upload(provider, auth, session, data)

    assert result.complete and confirmed[0] == 5 * MIB  # asked TikTok first; nothing resent
    assert mock.publishes[publish_id]["bytes"] == data
    assert len(mock.calls(INIT_URL)) == 1  # the same post, never a second one


def test_a_range_tiktok_does_not_expect_is_recovered_by_asking(provider, mock):
    data = b"\x05" * (11 * MIB)
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))
    statuses_before = len(mock.calls(STATUS_URL))
    mock.next_responses.extend(
        [ok({"status": "PROCESSING_UPLOAD", "uploaded_bytes": 0}), httpx.Response(416)]
    )

    result, _ = upload(provider, auth, session, data)

    assert result.complete
    assert len(mock.calls(STATUS_URL)) - statuses_before >= 2  # asked again after the 416


def test_an_expired_upload_url_needs_a_new_session(provider, mock):
    data = b"\x01" * (6 * MIB)
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))
    mock.publishes[tiktok.Session.load(session).publish_id]["expired"] = True

    with pytest.raises(PublishProviderError) as error:
        upload(provider, auth, session, data)

    assert error.value.code == PublishErrorCode.UPLOAD_SESSION_EXPIRED


def test_an_unreadable_session_is_an_expired_session(provider, mock):
    auth = provider.authorize("rt-0")
    for raw in ("", "not json", '{"p": "x"}', '{"p":"x","u":"http://insecure","c":5,"n":1}'):
        with pytest.raises(PublishProviderError) as error:
            provider.query_upload(auth, raw, 10)
        assert error.value.code == PublishErrorCode.UPLOAD_SESSION_EXPIRED


# --- what happened to the post ------------------------------------------------------------


def test_status_follows_tiktok_and_never_runs_ahead(provider, mock):
    data = b"\x02" * 4096
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))
    publish_id = upload(provider, auth, session, data)[0].video_id

    assert provider.video_status(auth, publish_id).upload == UploadState.UPLOADED  # processing
    assert provider.video_status(auth, publish_id).upload == UploadState.PROCESSED


@pytest.mark.parametrize(
    ("reason", "state"),
    [
        ("file_format_check_failed", UploadState.FAILED),
        ("duration_check_failed", UploadState.FAILED),
        ("spam_risk_user_banned_from_posting", UploadState.REJECTED),
        ("auth_removed", UploadState.REJECTED),
    ],
)
def test_a_failed_post_reports_tiktoks_reason(provider, mock, reason, state):
    data = b"\x02" * 4096
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))
    publish_id = upload(provider, auth, session, data)[0].video_id
    mock.publishes[publish_id]["fail_reason"] = reason

    status = provider.video_status(auth, publish_id)

    assert (status.upload, status.reason) == (state, reason)


def test_a_post_that_failed_during_upload_stops_the_upload(provider, mock):
    data = b"\x03" * (11 * MIB)
    auth = provider.authorize("rt-0")
    session = provider.start_upload(auth, request(len(data)))
    mock.publishes[tiktok.Session.load(session).publish_id]["fail_reason"] = (
        "file_format_check_failed"
    )

    with pytest.raises(PublishProviderError) as error:
        upload(provider, auth, session, data)

    assert error.value.code == PublishErrorCode.PROCESSING_FAILED and not error.value.retryable


# --- the whole pipeline -------------------------------------------------------------------


def test_the_pipeline_publishes_to_tiktok(db_session: Session, tmp_path, mock, provider):
    data = b"\x04" * (6 * MIB + 17)
    storage = LocalStorageProvider(tmp_path / "media")
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(data), edit.storage_key)
    connection = connections.save_connection(
        db_session, CIPHER, user_id=user.id, refresh_token="rt-0", account_id="open-id-1",
        account_title="@amine.clips", scopes=["video.publish"],
        provider=PublishingProvider.TIKTOK,
    )  # fmt: skip
    options = {"privacy_level": "SELF_ONLY", "allow_comment": True}
    job, created = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connection, task_id="task-1",
        metadata=PublishMetadata.create(title="Pricing", description="How I priced it"),
        options=options, platform="TikTok",
    )  # fmt: skip
    assert created and job.provider == "tiktok" and job.options == options
    scheduled: list = []

    pipeline.publish_short(
        job.id, db_session, settings=settings(), storage=storage, provider=provider,
        task_id="task-1", sleep=lambda s: None,
        schedule_status_check=lambda job_id, delay: scheduled.append(job_id),
    )  # fmt: skip

    assert job.status == PublishStatus.UPLOADED, (job.error_code, job.error_message)
    publish = mock.publishes[job.provider_video_id]
    assert publish["bytes"] == data and publish["post"]["disable_comment"] is False
    assert publish["post"]["title"] == "How I priced it"
    assert job.upload_session_ciphertext is None  # the upload URL is not kept once it is done
    assert scheduled == [job.id]
    # The rotated refresh token was kept: the next step authorizes with it, not the dead one.
    assert connections.refresh_token_of(db_session, CIPHER, connection) == "rt-1"

    pipeline.check_status(job.id, db_session, settings=settings(), provider=provider)
    pipeline.check_status(job.id, db_session, settings=settings(), provider=provider)
    assert job.status == PublishStatus.PUBLISHED  # only once TikTok said PUBLISH_COMPLETE
    # Each check rotated the token again; what is stored is always the one TikTok still accepts.
    kept = connections.refresh_token_of(db_session, CIPHER, connection)
    assert kept != "rt-1" and mock.refresh_tokens == {kept}


def test_the_same_post_with_other_choices_is_another_job():
    base = {"connection_id": uuid.uuid4(), "edit_id": uuid.uuid4(),
            "metadata": PublishMetadata.create(title="Pricing")}  # fmt: skip
    plain = fingerprint(**base)
    assert fingerprint(**base, options={}) == plain  # YouTube jobs keep their fingerprints
    assert fingerprint(**base, options={"privacy_level": "SELF_ONLY"}) != plain
    assert fingerprint(**base, options={"privacy_level": "SELF_ONLY"}) != fingerprint(
        **base, options={"privacy_level": "PUBLIC_TO_EVERYONE"}
    )


# --- configuration ------------------------------------------------------------------------


def test_tiktok_settings_are_checked_only_when_it_is_switched_on():
    off = Settings(**{**get_settings().model_dump(), "tiktok_publishing_enabled": False})
    assert not [p for p in publishing_problems(off) if "TIKTOK" in p]
    assert not [p for p in publishing_problems(settings()) if "TIKTOK" in p]

    # Switched on with bad values, the server refuses to start and names each setting.
    with pytest.raises(ValidationError) as refused:
        settings(
            tiktok_client_key="",
            tiktok_client_secret="",
            tiktok_oauth_redirect_uri="http://localhost:8000/publishing/tiktok/callback",
            tiktok_upload_chunk_bytes=100_000_000,
        )
    problems = str(refused.value)
    for name in (
        "TIKTOK_CLIENT_KEY",
        "TIKTOK_CLIENT_SECRET",
        "TIKTOK_OAUTH_REDIRECT_URI",
        "TIKTOK_UPLOAD_CHUNK_BYTES",
    ):
        assert name in problems
    assert "localhost:8000" not in problems  # by name only, never the value
