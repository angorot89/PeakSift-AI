"""The resumable upload loop: resume from the provider's offset, monotonic progress,
ownership checks, bounded retries — and never a second video."""

import os

import pytest

from app.services.publishing.fake import FakePublishingProvider
from app.services.publishing.provider import PublishErrorCode, PublishProviderError, VideoRequest
from app.services.publishing.uploader import UploadSource, run_upload
from tests.youtube_mock import MockYouTube

REFRESH = "1//0gUploaderRefreshToken"
DATA = os.urandom(10_000)


class Superseded(Exception):
    pass


def source(data: bytes = DATA, reads: list | None = None) -> UploadSource:
    def read(offset: int, length: int) -> bytes:
        if reads is not None:
            reads.append((offset, length))
        return data[offset : offset + length]

    return UploadSource(len(data), read)


def begin(provider, size: int = len(DATA)):
    auth = provider.authorize(REFRESH)
    request = VideoRequest(title="t", description="", tags=(), privacy="private",
                           made_for_kids=False, category_id="22", size_bytes=size)  # fmt: skip
    return auth, provider.start_upload(auth, request)


def upload(provider, auth, uri, *, src: UploadSource | None = None, **kwargs):
    progress: list[int] = []
    options = {"chunk_bytes": 4096, "on_progress": progress.append,
               "still_owner": lambda: None, "sleep": lambda s: None, **kwargs}  # fmt: skip
    result = run_upload(provider, auth, uri, src or source(), **options)
    return result, progress


def test_a_whole_upload_reports_real_monotonic_progress():
    provider = FakePublishingProvider()
    auth, uri = begin(provider)
    reads: list = []
    result, progress = upload(provider, auth, uri, src=source(reads=reads))
    assert result.complete and list(provider.videos.values())[0]["data"] == DATA
    assert progress == [0, 4096, 8192, 10_000] and progress == sorted(set(progress))
    assert reads == [(0, 4096), (4096, 4096), (8192, 1808)]


def test_partial_acceptance_resends_only_what_was_not_stored():
    provider = FakePublishingProvider(confirm_at_most=1000)
    auth, uri = begin(provider)
    reads: list = []
    result, progress = upload(provider, auth, uri, src=source(reads=reads))
    assert result.complete and list(provider.videos.values())[0]["data"] == DATA
    assert [offset for offset, _ in reads] == list(range(0, 10_000, 1000))
    assert progress[-1] == 10_000 and progress == sorted(progress)


def test_a_restarted_worker_resumes_from_youtubes_offset_without_a_second_video():
    server = MockYouTube()
    from app.services.publishing.youtube import YouTubeProvider

    provider = YouTubeProvider(server.refresh, client=server.client())
    auth, uri = begin(provider)
    provider.upload_chunk(auth, uri, DATA[:4096], 0, len(DATA))  # ...then the worker dies

    reads: list = []
    result, progress = upload(provider, provider.authorize(REFRESH), uri,
                              src=source(reads=reads))  # fmt: skip

    assert reads[0] == (4096, 4096)  # nothing YouTube already had was sent again
    assert progress[0] == 4096 and result.complete
    assert len(server.videos) == 1 and server.videos[result.video_id]["data"] == DATA


def test_transient_failures_are_retried_with_backoff_then_succeed():
    provider = FakePublishingProvider()
    provider.fail("upload_chunk", [None, PublishErrorCode.NETWORK_ERROR,
                                   PublishErrorCode.RATE_LIMITED])  # fmt: skip
    auth, uri = begin(provider)
    sleeps: list[float] = []
    result, progress = upload(provider, auth, uri, sleep=sleeps.append)
    assert result.complete and len(provider.videos) == 1
    assert sleeps == [2.0, 4.0] and progress == sorted(progress)


def test_retries_are_bounded():
    provider = FakePublishingProvider()
    provider.fail("upload_chunk", [PublishErrorCode.PROVIDER_ERROR] * 10)
    auth, uri = begin(provider)
    with pytest.raises(PublishProviderError) as excinfo:
        upload(provider, auth, uri, max_retries=3)
    assert excinfo.value.code == PublishErrorCode.PROVIDER_ERROR
    assert provider.calls.count("upload_chunk") == 4 and provider.videos == {}


@pytest.mark.parametrize(
    "code",
    [
        PublishErrorCode.QUOTA_EXCEEDED,
        PublishErrorCode.AUTHENTICATION_REQUIRED,
        PublishErrorCode.INVALID_METADATA,
        PublishErrorCode.UPLOAD_SESSION_EXPIRED,
    ],  # fmt: skip
)
def test_non_retryable_failures_stop_at_once(code):
    provider = FakePublishingProvider()
    provider.fail("upload_chunk", [code])
    auth, uri = begin(provider)
    with pytest.raises(PublishProviderError) as excinfo:
        upload(provider, auth, uri)
    assert excinfo.value.code == code and provider.calls.count("upload_chunk") == 1


def test_a_fenced_out_attempt_stops_before_sending_more():
    provider = FakePublishingProvider()
    auth, uri = begin(provider)
    checks = {"n": 0}

    def still_owner():
        checks["n"] += 1
        if checks["n"] == 3:
            raise Superseded()

    with pytest.raises(Superseded):
        upload(provider, auth, uri, still_owner=still_owner)
    assert len(provider.sessions[uri]["received"]) == 4096 and provider.videos == {}


def test_a_provider_that_goes_backwards_is_an_error():
    from app.services.publishing.provider import UploadProgress

    provider = FakePublishingProvider()
    auth, uri = begin(provider)
    answers = iter([UploadProgress(5000), UploadProgress(100)])
    provider.query_upload = lambda *a: next(answers)  # type: ignore[method-assign]
    provider.upload_chunk = lambda *a: next(answers)  # type: ignore[method-assign]
    with pytest.raises(PublishProviderError):
        upload(provider, auth, uri, max_retries=0)


def test_a_short_read_from_storage_is_not_sent():
    provider = FakePublishingProvider()
    auth, uri = begin(provider)
    broken = UploadSource(len(DATA), lambda offset, length: DATA[offset : offset + length - 1])
    with pytest.raises(OSError):
        upload(provider, auth, uri, src=broken)
    assert len(provider.sessions[uri]["received"]) == 0
