"""YouTube-specific behaviour of the resumable upload provider (mocked server, no network)."""

import json
import logging

import pytest

from app.core.config import Settings, get_settings
from app.services.publishing import youtube
from app.services.publishing.provider import (
    PublishErrorCode,
    PublishProviderError,
    UploadState,
    VideoRequest,
)
from app.services.publishing.youtube import YouTubeProvider, classify
from tests.youtube_mock import MockYouTube, google_error

REFRESH = "1//0gUploadTestRefreshToken"
DATA = bytes(range(256)) * 4  # 1024 bytes


def request(**overrides) -> VideoRequest:
    fields = dict(title="Héllo 🎬", description="Line one\nLine two", tags=("a b", "c"),
                  privacy="private", made_for_kids=False, category_id="22",
                  size_bytes=len(DATA))  # fmt: skip
    fields.update(overrides)
    return VideoRequest(**fields)


@pytest.fixture
def server() -> MockYouTube:
    return MockYouTube()


@pytest.fixture
def provider(server) -> YouTubeProvider:
    return YouTubeProvider(server.refresh, client=server.client())


def test_the_session_request_follows_googles_resumable_protocol(server, provider):
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, request())

    [start] = server.requests
    assert start.method == "POST" and str(start.url).startswith(youtube.UPLOAD_URL)
    assert dict(start.url.params) == {"uploadType": "resumable", "part": "snippet,status"}
    assert start.headers["x-upload-content-length"] == str(len(DATA))
    assert start.headers["x-upload-content-type"] == "video/mp4"
    assert start.headers["authorization"] == f"Bearer {auth.access_token}"
    body = json.loads(start.content)
    assert body == {
        "snippet": {"title": "Héllo 🎬", "description": "Line one\nLine two",
                    "tags": ["a b", "c"], "categoryId": "22"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }  # fmt: skip
    assert uri.startswith("https://") and "upload_id=" in uri


def test_chunks_carry_content_ranges_and_resume_from_youtubes_range(server, provider):
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, request())
    server.confirm_at_most = 300  # YouTube stores only part of what was sent

    first = provider.upload_chunk(auth, uri, DATA[:512], 0, len(DATA))
    assert first.confirmed_bytes == 300 and not first.complete
    assert server.requests[-1].headers["content-range"] == f"bytes 0-511/{len(DATA)}"

    server.confirm_at_most = None
    done = provider.upload_chunk(auth, uri, DATA[300:], 300, len(DATA))
    assert server.requests[-1].headers["content-range"] == f"bytes 300-1023/{len(DATA)}"
    assert done.complete and done.confirmed_bytes == len(DATA)
    assert (done.channel_id, done.channel_title) == ("UCmock", "Mock")
    assert server.videos[done.video_id]["data"] == DATA


def test_asking_where_an_upload_stands_uses_an_empty_put(server, provider):
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, request())
    assert provider.query_upload(auth, uri, len(DATA)).confirmed_bytes == 0  # 308, no Range
    provider.upload_chunk(auth, uri, DATA[:100], 0, len(DATA))
    progress = provider.query_upload(auth, uri, len(DATA))
    query = server.requests[-1]
    assert query.method == "PUT" and query.content == b""
    assert query.headers["content-range"] == f"bytes */{len(DATA)}"
    assert progress.confirmed_bytes == 100


@pytest.mark.parametrize(
    ("status", "reason", "code"),
    [
        (401, "authError", PublishErrorCode.AUTHENTICATION_REQUIRED),
        (403, "quotaExceeded", PublishErrorCode.QUOTA_EXCEEDED),
        (403, "uploadLimitExceeded", PublishErrorCode.QUOTA_EXCEEDED),
        (403, "rateLimitExceeded", PublishErrorCode.RATE_LIMITED),
        (429, "", PublishErrorCode.RATE_LIMITED),
        (403, "forbidden", PublishErrorCode.PERMISSION_DENIED),
        (403, "youtubeSignupRequired", PublishErrorCode.PERMISSION_DENIED),
        (400, "invalidTitle", PublishErrorCode.INVALID_METADATA),
        (400, "invalidTags", PublishErrorCode.INVALID_METADATA),
        (500, "backendError", PublishErrorCode.PROVIDER_ERROR),
        (503, "", PublishErrorCode.PROVIDER_ERROR),
    ],
)
def test_google_errors_become_normalized_codes(server, provider, status, reason, code):
    server.next_responses.append(google_error(status, reason, "contains private details"))
    with pytest.raises(PublishProviderError) as excinfo:
        provider.start_upload(provider.authorize(REFRESH), request())
    assert excinfo.value.code == code
    assert "private details" not in excinfo.value.message  # Google's text never surfaces


@pytest.mark.parametrize("status", [404, 410])
def test_a_vanished_session_is_an_expired_session(status):
    assert classify(status, set(), session=True) == PublishErrorCode.UPLOAD_SESSION_EXPIRED
    assert classify(status, set()) == PublishErrorCode.PROVIDER_ERROR


def test_network_failures_are_retryable_network_errors(server):
    import httpx

    def broken(request):
        raise httpx.ConnectTimeout("timed out talking to upload.example")

    provider = YouTubeProvider(
        server.refresh, client=httpx.Client(transport=httpx.MockTransport(broken))
    )
    with pytest.raises(PublishProviderError) as excinfo:
        provider.start_upload(provider.authorize(REFRESH), request())
    assert excinfo.value.code == PublishErrorCode.NETWORK_ERROR and excinfo.value.retryable


def test_a_missing_location_or_video_id_is_a_provider_error(server, provider):
    import httpx

    server.next_responses.append(httpx.Response(200))  # no Location header
    with pytest.raises(PublishProviderError) as excinfo:
        provider.start_upload(provider.authorize(REFRESH), request())
    assert excinfo.value.code == PublishErrorCode.PROVIDER_ERROR


def test_processing_status_is_honestly_unknown_with_the_upload_only_scope():
    server = MockYouTube(status_scope=False)
    provider = YouTubeProvider(server.refresh, client=server.client())
    assert provider.video_status(provider.authorize(REFRESH), "vid1").upload == UploadState.UNKNOWN


def test_processing_status_is_read_when_youtube_allows_it(server, provider):
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, request())
    video_id = provider.upload_chunk(auth, uri, DATA, 0, len(DATA)).video_id
    status = provider.video_status(auth, video_id)
    assert status.upload == UploadState.PROCESSED and status.privacy == "private"
    assert provider.video_status(auth, "missing").upload == UploadState.DELETED


def test_logs_never_contain_tokens_or_session_uris(server, provider, caplog):
    caplog.set_level(logging.DEBUG)
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, request())
    server.next_responses.append(google_error(403, "quotaExceeded"))
    with pytest.raises(PublishProviderError):
        provider.upload_chunk(auth, uri, DATA, 0, len(DATA))
    assert "quotaExceeded" in caplog.text  # the reason is logged for operators...
    for secret in (auth.access_token, uri, "ADPy0secret", REFRESH):
        assert secret not in caplog.text  # ...credentials and the session never are


# --- authorization through google-auth -----


def test_refresh_uses_google_auth_and_maps_its_failures(monkeypatch):
    from google.auth.exceptions import RefreshError, TransportError
    from google.oauth2.credentials import Credentials

    google = {"google_client_id": "x.apps.googleusercontent.com", "google_client_secret": "s"}
    settings = Settings(**{**get_settings().model_dump(), **google})
    outcomes = iter([None, RefreshError("invalid_grant"), TransportError("down")])

    def fake_refresh(self, request):
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        assert self.refresh_token == REFRESH and self.token_uri == youtube.TOKEN_URI
        assert self.scopes == [youtube.UPLOAD_SCOPE]
        self.token = "ya29.fresh"

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    refresh = youtube._refresh_with_google(settings)
    assert refresh(REFRESH) == "ya29.fresh"
    for expected in (PublishErrorCode.AUTHENTICATION_REQUIRED, PublishErrorCode.NETWORK_ERROR):
        with pytest.raises(PublishProviderError) as excinfo:
            refresh(REFRESH)
        assert excinfo.value.code == expected


@pytest.mark.parametrize("size", [1, 256 * 1024 + 1, 3 * 1024 * 1024 + 7])
def test_chunk_sizes_must_be_multiples_of_256_kib(size):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        Settings(**{**get_settings().model_dump(), "youtube_upload_chunk_bytes": size})
    assert "YOUTUBE_UPLOAD_CHUNK_BYTES" in str(excinfo.value) or "greater than" in str(
        excinfo.value
    )


def test_the_factory_builds_youtube_or_the_fake_outside_production():
    from app.services.publishing.factory import get_publishing_provider

    base = {**get_settings().model_dump(), "google_client_id": "x.apps.googleusercontent.com",
            "google_client_secret": "s"}  # fmt: skip
    assert get_publishing_provider(Settings(**base)).name == "youtube"
    fake = Settings(**{**base, "publishing_provider": "fake"})
    assert get_publishing_provider(fake) is get_publishing_provider(fake)  # one per process

    production = Settings.model_construct(**{**fake.model_dump(), "app_env": "production"})
    with pytest.raises(RuntimeError):
        get_publishing_provider(production)


def test_simulated_ids_stay_unique_across_processes():
    """A restarted worker must not hand out an id an earlier simulated upload already has."""
    from app.services.publishing.fake import FakePublishingProvider

    def upload(provider):
        auth = provider.authorize("refresh")
        uri = provider.start_upload(auth, request(size_bytes=4))
        return provider.upload_chunk(auth, uri, b"data", 0, 4).video_id

    assert upload(FakePublishingProvider()) == "fake-000001"  # tests stay deterministic
    first, second = (upload(FakePublishingProvider(id_prefix=p)) for p in ("a1b2", "c3d4"))
    assert first == "fake-a1b2-000001" and first != second
