"""The publishing provider contract, run unchanged against every implementation.

Each implementation supplies a harness: the provider plus the few test-only controls the
scenarios need (expire a session, revoke a token, list created videos). The YouTube
implementation joins this suite with a mocked YouTube server.
"""

import os

import pytest

from app.core.config import Settings, get_settings
from app.services.publishing.fake import FakePublishingProvider
from app.services.publishing.provider import (
    ProviderAuth,
    PublishErrorCode,
    PublishProviderError,
    UploadState,
    VideoRequest,
)

REFRESH = "1//0gContractRefreshToken"
DATA = os.urandom(1000)


class FakeHarness:
    def __init__(self, **options) -> None:
        self.provider = FakePublishingProvider(**options)

    def expire(self, uri: str) -> None:
        self.provider.expire(uri)

    def revoke(self, token: str) -> None:
        self.provider.revoked_tokens.add(token)

    def videos(self) -> dict[str, bytes]:
        return {vid: video["data"] for vid, video in self.provider.videos.items()}


HARNESSES = {"fake": FakeHarness}


@pytest.fixture(params=sorted(HARNESSES))
def make(request):
    return HARNESSES[request.param]


def video(size: int = len(DATA), **overrides) -> VideoRequest:
    fields = dict(title="Contract test", description="d", tags=("t",), privacy="private",
                  made_for_kids=False, category_id="22", size_bytes=size)  # fmt: skip
    fields.update(overrides)
    return VideoRequest(**fields)


def send(provider, auth, uri, data: bytes, *, chunk: int, start: int = 0):
    """Upload from ``start`` the way the pipeline does: always from the confirmed offset."""
    offset, progress = start, None
    while offset < len(data):
        progress = provider.upload_chunk(auth, uri, data[offset : offset + chunk], offset,
                                         len(data))  # fmt: skip
        assert progress.confirmed_bytes >= offset  # never goes backwards
        offset = progress.confirmed_bytes
    return progress


def test_a_video_uploads_in_chunks_and_is_created_once(make):
    harness = make()
    provider = harness.provider
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, video())

    progress = send(provider, auth, uri, DATA, chunk=256)

    assert progress.complete and progress.confirmed_bytes == len(DATA)
    assert harness.videos() == {progress.video_id: DATA}


def test_an_interrupted_upload_resumes_where_the_provider_stopped(make):
    harness = make()
    provider = harness.provider
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, video())
    provider.upload_chunk(auth, uri, DATA[:300], 0, len(DATA))
    # ...the worker dies; a new attempt asks the provider where the upload stands.
    resumed = provider.query_upload(provider.authorize(REFRESH), uri, len(DATA))
    assert resumed.confirmed_bytes == 300 and not resumed.complete

    progress = send(provider, auth, uri, DATA, chunk=256, start=resumed.confirmed_bytes)

    assert progress.complete and list(harness.videos().values()) == [DATA]


def test_bytes_at_the_wrong_offset_are_not_accepted(make):
    harness = make()
    provider = harness.provider
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, video())
    provider.upload_chunk(auth, uri, DATA[:100], 0, len(DATA))

    replay = provider.upload_chunk(auth, uri, DATA[:100], 0, len(DATA))  # duplicate send
    assert replay.confirmed_bytes == 100
    progress = send(provider, auth, uri, DATA, chunk=500, start=100)
    assert list(harness.videos().values()) == [DATA]  # no duplicated bytes
    assert progress.complete


def test_a_completed_upload_queried_again_reports_the_same_video(make):
    harness = make()
    provider = harness.provider
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, video())
    done = send(provider, auth, uri, DATA, chunk=len(DATA))
    again = provider.query_upload(auth, uri, len(DATA))
    assert again.complete and again.video_id == done.video_id and len(harness.videos()) == 1


def test_an_expired_session_is_reported_as_such(make):
    harness = make()
    provider = harness.provider
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, video())
    harness.expire(uri)
    for call in (lambda: provider.query_upload(auth, uri, len(DATA)),
                 lambda: provider.upload_chunk(auth, uri, DATA, 0, len(DATA))):  # fmt: skip
        with pytest.raises(PublishProviderError) as excinfo:
            call()
        assert excinfo.value.code == PublishErrorCode.UPLOAD_SESSION_EXPIRED
        assert excinfo.value.retryable


def test_a_revoked_account_needs_reconnecting(make):
    harness = make()
    harness.revoke(REFRESH)
    with pytest.raises(PublishProviderError) as excinfo:
        harness.provider.authorize(REFRESH)
    assert excinfo.value.code == PublishErrorCode.AUTHENTICATION_REQUIRED
    assert not excinfo.value.retryable


def test_processing_is_reported_until_the_video_is_processed(make):
    harness = make(processing_polls=2) if make is FakeHarness else make()
    provider = harness.provider
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, video())
    video_id = send(provider, auth, uri, DATA, chunk=len(DATA)).video_id
    states = [provider.video_status(auth, video_id).upload for _ in range(3)]
    assert states[0] in (UploadState.UPLOADED, UploadState.PROCESSED)
    assert states[-1] == UploadState.PROCESSED


def test_credentials_never_show_in_reprs():
    assert "secret-access" not in repr(ProviderAuth("secret-access-token"))


@pytest.mark.parametrize("code", list(PublishErrorCode))
def test_every_error_has_a_safe_message_and_a_retry_decision(code):
    error = PublishProviderError(code)
    assert error.message and "http" not in error.message.lower()
    assert error.retryable == (
        code in {PublishErrorCode.RATE_LIMITED, PublishErrorCode.NETWORK_ERROR,
                 PublishErrorCode.PROVIDER_ERROR, PublishErrorCode.UPLOAD_SESSION_EXPIRED}
    )  # fmt: skip


# --- the fake specifically -----


def test_the_fake_can_confirm_less_than_it_was_sent():
    provider = FakePublishingProvider(confirm_at_most=64)
    auth = provider.authorize(REFRESH)
    uri = provider.start_upload(auth, video())
    first = provider.upload_chunk(auth, uri, DATA[:256], 0, len(DATA))
    assert first.confirmed_bytes == 64
    assert send(provider, auth, uri, DATA, chunk=256, start=64).complete
    assert list(provider.videos.values())[0]["data"] == DATA


def test_the_fake_scripts_failures_per_operation():
    provider = FakePublishingProvider()
    provider.fail("start_upload", [PublishErrorCode.QUOTA_EXCEEDED, None])
    auth = provider.authorize(REFRESH)
    with pytest.raises(PublishProviderError) as excinfo:
        provider.start_upload(auth, video())
    assert excinfo.value.code == PublishErrorCode.QUOTA_EXCEEDED
    assert provider.start_upload(auth, video()).startswith("https://upload.fake.invalid/")


def test_production_refuses_the_fake_provider():
    from app.core.config import production_problems

    settings = Settings.model_construct(
        **{**get_settings().model_dump(), "publishing_provider": "fake"}
    )
    assert "PUBLISHING_PROVIDER must be youtube" in production_problems(settings)
