"""The publishing pipeline end to end on the fake provider, real storage and database:
uploads resume after crashes without a second video, accounts that need reconnecting are
marked, processing is followed honestly, and secrets never reach the logs."""

import io
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ConnectionStatus, PublishingConnection, PublishJob, PublishStatus
from app.services.publishing import pipeline
from app.services.publishing.fake import FakePublishingProvider
from app.services.publishing.jobs import request_publish
from app.services.publishing.metadata import PublishMetadata
from app.services.publishing.provider import PublishErrorCode, UploadState
from app.services.storage import LocalStorageProvider
from tests.publishing_fixtures import KEY, REFRESH_TOKEN, connect, ready_edit

CHUNK = 256 * 1024
DATA = os.urandom(3 * CHUNK + 12_345)


class Crash(BaseException):
    """A worker dying mid-job (not an Exception: nothing in the pipeline catches it)."""


@pytest.fixture
def settings() -> Settings:
    overrides = {"publishing_token_encryption_key": KEY, "youtube_upload_chunk_bytes": CHUNK,
                 "publish_status_max_polls": 5}  # fmt: skip
    return Settings(**{**get_settings().model_dump(), **overrides})


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "media")


@pytest.fixture
def setup(db_session: Session, storage):
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(DATA), edit.storage_key)
    connection = connect(db_session, user)
    job, _ = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connection, task_id="task-1",
        metadata=PublishMetadata.create(title="Pipeline test", tags=["peaksift"]),
    )  # fmt: skip
    return {"user": user, "edit": edit, "connection": connection, "job": job}


def run(job, db, settings, storage, provider, task_id="task-1", scheduled=None):
    return pipeline.publish_short(
        job.id, db, settings=settings, storage=storage, provider=provider, task_id=task_id,
        sleep=lambda seconds: None,
        schedule_status_check=(lambda job_id, delay: scheduled.append(delay))
        if scheduled is not None else None,
    )  # fmt: skip


def retry(job: PublishJob, db: Session, task_id: str) -> None:
    """What the retry endpoint does: a fresh attempt token on the same row."""
    job.status, job.celery_task_id, job.attempt = PublishStatus.QUEUED, task_id, job.attempt + 1
    db.commit()


def videos(provider: FakePublishingProvider) -> list[bytes]:
    return [video["data"] for video in provider.videos.values()]


# --- the happy path -----


def test_a_short_is_uploaded_then_followed_until_published(db_session, settings, storage, setup):
    provider = FakePublishingProvider(processing_polls=2)
    scheduled: list[int] = []
    job = run(setup["job"], db_session, settings, storage, provider, scheduled=scheduled)

    assert job.status == PublishStatus.UPLOADED and job.progress_percent == 100
    assert job.provider_video_id.startswith("fake-") and videos(provider) == [DATA]
    assert job.bytes_uploaded == job.bytes_total == len(DATA)
    assert job.upload_session_ciphertext is None  # the session secret is gone once done
    assert scheduled == [settings.publish_status_poll_seconds]
    db_session.refresh(setup["connection"])
    assert setup["connection"].account_title == "Simulated channel"  # learned from the upload
    request = list(provider.videos.values())[0]["request"]
    assert (request.title, request.tags, request.privacy) == ("Pipeline test", ("peaksift",),
                                                              "private")  # fmt: skip

    scheduled.clear()
    hook = lambda job_id, delay: scheduled.append(delay)  # noqa: E731
    pipeline.check_status(job.id, db_session, settings=settings, provider=provider,
                          schedule_status_check=hook)  # fmt: skip
    assert job.status == PublishStatus.PROCESSING and scheduled == [30]
    pipeline.check_status(job.id, db_session, settings=settings, provider=provider,
                          schedule_status_check=hook)  # fmt: skip
    assert job.status == PublishStatus.PUBLISHED and job.published_at is not None


def test_progress_is_real_and_never_goes_backwards(db_session, settings, storage, setup):
    seen: list[int] = []
    provider = FakePublishingProvider(confirm_at_most=100_000)
    original = provider.upload_chunk

    def spying(*args):
        db_session.refresh(setup["job"])
        seen.append(setup["job"].progress_percent)
        return original(*args)

    provider.upload_chunk = spying  # type: ignore[method-assign]
    run(setup["job"], db_session, settings, storage, provider)
    assert seen == sorted(seen) and seen[0] == 0 and max(seen) < 100
    assert setup["job"].progress_percent == 100


# --- crashes and retries never duplicate -----


def test_a_killed_worker_resumes_the_same_session(db_session, settings, storage, setup):
    provider = FakePublishingProvider()
    calls = {"n": 0}
    original = provider.upload_chunk

    def dies_after_two_chunks(*args):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash()
        return original(*args)

    provider.upload_chunk = dies_after_two_chunks  # type: ignore[method-assign]
    with pytest.raises(Crash):
        run(setup["job"], db_session, settings, storage, provider)
    job = setup["job"]
    db_session.refresh(job)
    assert job.status == PublishStatus.UPLOADING and job.upload_session_ciphertext
    assert job.bytes_uploaded == 2 * CHUNK

    provider.upload_chunk = original  # type: ignore[method-assign]
    job.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)  # the attempt went stale
    retry(job, db_session, "task-2")
    run(job, db_session, settings, storage, provider, task_id="task-2")

    assert job.status == PublishStatus.UPLOADED and videos(provider) == [DATA]
    assert len(provider.sessions) == 1  # resumed, not restarted


def test_a_crash_after_the_last_byte_does_not_upload_again(db_session, settings, storage, setup):
    provider = FakePublishingProvider()
    original = provider.upload_chunk

    def dies_after_completion(*args):
        progress = original(*args)
        if progress.complete:
            raise Crash()  # YouTube has the video; PeakSift never recorded it
        return progress

    provider.upload_chunk = dies_after_completion  # type: ignore[method-assign]
    with pytest.raises(Crash):
        run(setup["job"], db_session, settings, storage, provider)
    provider.upload_chunk = original  # type: ignore[method-assign]
    job = setup["job"]
    db_session.refresh(job)
    job.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
    retry(job, db_session, "task-2")
    run(job, db_session, settings, storage, provider, task_id="task-2")

    assert job.status == PublishStatus.UPLOADED and len(provider.videos) == 1
    assert job.provider_video_id == next(iter(provider.videos))


def test_a_failed_job_retried_resumes_and_a_finished_one_never_reuploads(
    db_session, settings, storage, setup
):
    provider = FakePublishingProvider()
    provider.fail("upload_chunk", [None] + [PublishErrorCode.NETWORK_ERROR] * 6)
    job = run(setup["job"], db_session, settings, storage, provider)
    assert job.status == PublishStatus.FAILED and job.error_code == "network_error"
    assert job.upload_session_ciphertext is not None  # kept so the retry can resume

    retry(job, db_session, "task-2")
    run(job, db_session, settings, storage, provider, task_id="task-2")
    assert job.status == PublishStatus.UPLOADED and videos(provider) == [DATA]

    retry(job, db_session, "task-3")  # even if asked again, the video exists: no upload
    run(job, db_session, settings, storage, provider, task_id="task-3")
    assert job.status == PublishStatus.UPLOADED and len(provider.videos) == 1
    assert provider.calls.count("start_upload") == 1


def test_an_expired_session_is_replaced_once(db_session, settings, storage, setup):
    provider = FakePublishingProvider()
    original = provider.upload_chunk
    expired = {"done": False}

    def expire_once(auth, uri, *rest):
        if not expired["done"] and len(provider.sessions[uri]["received"]) >= CHUNK:
            expired["done"] = True
            provider.expire(uri)
        return original(auth, uri, *rest)

    provider.upload_chunk = expire_once  # type: ignore[method-assign]
    job = run(setup["job"], db_session, settings, storage, provider)
    assert job.status == PublishStatus.UPLOADED and videos(provider) == [DATA]
    assert provider.calls.count("start_upload") == 2


def test_a_session_that_keeps_expiring_fails_the_attempt(db_session, settings, storage, setup):
    provider = FakePublishingProvider()
    provider.fail("query_upload", [PublishErrorCode.UPLOAD_SESSION_EXPIRED] * 2)
    job = run(setup["job"], db_session, settings, storage, provider)
    assert job.status == PublishStatus.FAILED and job.error_code == "upload_session_expired"
    assert provider.videos == {}


# --- accounts, sources and the provider refusing -----


def test_a_revoked_account_needs_reconnecting(db_session, settings, storage, setup):
    provider = FakePublishingProvider()
    provider.revoked_tokens.add(REFRESH_TOKEN)
    job = run(setup["job"], db_session, settings, storage, provider)
    assert job.status == PublishStatus.FAILED and job.error_code == "authentication_required"
    db_session.refresh(setup["connection"])
    assert setup["connection"].status == ConnectionStatus.NEEDS_RECONNECT
    assert provider.calls.count("start_upload") == 0


def test_a_token_no_key_can_open_needs_reconnecting(db_session, storage, setup):
    from app.services.publishing.tokens import generate_key

    other_key = Settings(**{**get_settings().model_dump(),
                            "publishing_token_encryption_key": generate_key()})  # fmt: skip
    job = run(setup["job"], db_session, other_key, storage, FakePublishingProvider())
    assert job.error_code == "authentication_required"
    db_session.refresh(setup["connection"])
    assert setup["connection"].status == ConnectionStatus.NEEDS_RECONNECT


def test_a_disconnected_account_fails_the_job(db_session, settings, storage, setup):
    db_session.delete(db_session.get(PublishingConnection, setup["connection"].id))
    db_session.commit()
    job = run(setup["job"], db_session, settings, storage, FakePublishingProvider())
    assert job.status == PublishStatus.FAILED and job.error_code == "not_connected"


def test_the_source_must_still_be_a_ready_file(db_session, settings, storage, setup):
    storage.delete(setup["edit"].storage_key)
    job = run(setup["job"], db_session, settings, storage, FakePublishingProvider())
    assert job.error_code == "edit_missing"
    setup["edit"].status = "failed"
    retry(job, db_session, "task-2")
    run(job, db_session, settings, storage, FakePublishingProvider(), task_id="task-2")
    assert job.error_code == "edit_not_ready"


@pytest.mark.parametrize(
    ("code", "operation"),
    [
        (PublishErrorCode.QUOTA_EXCEEDED, "start_upload"),
        (PublishErrorCode.INVALID_METADATA, "start_upload"),
        (PublishErrorCode.PERMISSION_DENIED, "authorize"),
    ],  # fmt: skip
)
def test_provider_refusals_fail_with_their_code(db_session, settings, storage, setup, code,
                                                operation):  # fmt: skip
    provider = FakePublishingProvider()
    provider.fail(operation, [code])
    job = run(setup["job"], db_session, settings, storage, provider)
    assert job.status == PublishStatus.FAILED and job.error_code == code.value
    assert job.upload_session_ciphertext is None and provider.videos == {}


# --- fencing -----


def test_a_superseded_attempt_stops_without_writing(db_session, settings, storage, setup):
    provider = FakePublishingProvider()
    original = provider.upload_chunk

    def taken_over(*args):
        setup["job"].celery_task_id = "task-new"  # the retry endpoint fenced this attempt out
        db_session.commit()
        return original(*args)

    provider.upload_chunk = taken_over  # type: ignore[method-assign]
    job = run(setup["job"], db_session, settings, storage, provider)
    db_session.refresh(job)
    assert job.celery_task_id == "task-new" and job.error_code is None
    assert job.status == PublishStatus.UPLOADING and provider.videos == {}


def test_a_duplicate_delivery_does_nothing(db_session, settings, storage, setup):
    provider = FakePublishingProvider()
    run(setup["job"], db_session, settings, storage, provider)
    run(setup["job"], db_session, settings, storage, provider)  # redelivered message
    assert len(provider.videos) == 1 and provider.calls.count("start_upload") == 1


# --- processing outcomes -----


def test_youtube_with_the_upload_only_scope_ends_honestly_at_uploaded(
    db_session, settings, storage, setup
):
    from app.services.publishing.youtube import YouTubeProvider
    from tests.youtube_mock import MockYouTube

    server = MockYouTube(status_scope=False)
    provider = YouTubeProvider(server.refresh, client=server.client())
    job = run(setup["job"], db_session, settings, storage, provider)
    assert job.status == PublishStatus.UPLOADED
    assert list(server.videos.values())[0]["data"] == DATA

    scheduled: list[int] = []
    pipeline.check_status(job.id, db_session, settings=settings, provider=provider,
                          schedule_status_check=lambda j, d: scheduled.append(d))  # fmt: skip
    assert job.status == PublishStatus.UPLOADED and scheduled == []  # no claim of "published"
    assert job.provider_processing_status == "unknown"
    assert not pipeline.awaiting_processing(job, settings)  # nobody keeps waiting


def test_processing_is_awaited_only_while_a_check_is_due(db_session, settings, storage, setup):
    provider = FakePublishingProvider(processing_polls=2)
    job = run(setup["job"], db_session, settings, storage, provider)
    assert pipeline.awaiting_processing(job, settings)  # uploaded; the first check is due
    pipeline.check_status(job.id, db_session, settings=settings, provider=provider)
    assert job.status == PublishStatus.PROCESSING and pipeline.awaiting_processing(job, settings)
    pipeline.check_status(job.id, db_session, settings=settings, provider=provider)
    assert job.status == PublishStatus.PUBLISHED and not pipeline.awaiting_processing(job, settings)


def test_a_rejected_video_is_a_provider_failure(db_session, settings, storage, setup):
    provider = FakePublishingProvider(final_state=UploadState.REJECTED)
    job = run(setup["job"], db_session, settings, storage, provider)
    pipeline.check_status(job.id, db_session, settings=settings, provider=provider)
    assert job.status == PublishStatus.PROVIDER_FAILED
    assert job.error_code == "processing_failed" and "rejected" in job.error_message


def test_status_checks_are_bounded(db_session, settings, storage, setup):
    provider = FakePublishingProvider(processing_polls=100)
    job = run(setup["job"], db_session, settings, storage, provider)
    scheduled: list[int] = []
    for _ in range(10):
        pipeline.check_status(job.id, db_session, settings=settings, provider=provider,
                              schedule_status_check=lambda j, d: scheduled.append(d))  # fmt: skip
    assert job.status_checks == 5 and len(scheduled) == 4
    assert job.status == PublishStatus.PROCESSING


# --- secrets -----


def test_no_secret_reaches_the_logs(db_session, settings, storage, setup, caplog):
    caplog.set_level(logging.DEBUG)
    provider = FakePublishingProvider()
    provider.fail("upload_chunk", [None, PublishErrorCode.NETWORK_ERROR])
    run(setup["job"], db_session, settings, storage, provider)
    session_uri = next(iter(provider.sessions))
    for secret in (REFRESH_TOKEN, session_uri, KEY):
        assert secret not in caplog.text


def test_the_celery_task_runs_the_pipeline(db_session, settings, storage, setup, monkeypatch):
    from app.workers import publish_tasks

    class Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    provider = FakePublishingProvider()
    scheduled: list = []
    monkeypatch.setattr(publish_tasks, "SessionLocal", Borrowed)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "media_storage", lambda s: storage)
    monkeypatch.setattr(pipeline, "get_publishing_provider", lambda s, platform: provider)
    monkeypatch.setattr(publish_tasks, "schedule_status_check",
                        lambda job_id, delay: scheduled.append((job_id, delay)))  # fmt: skip
    publish_tasks.publish_short_task.apply(args=[str(setup["job"].id)], task_id="task-1")
    db_session.refresh(setup["job"])
    assert setup["job"].status == PublishStatus.UPLOADED
    assert scheduled == [(setup["job"].id, 30)]
    publish_tasks.publish_short_task.apply(args=["not-a-uuid"])  # ignored, logged
    assert uuid.UUID(str(setup["job"].id))
