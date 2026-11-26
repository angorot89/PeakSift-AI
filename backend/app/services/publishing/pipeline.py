"""Publishing one job: ``publish_short(publish_job_id)`` and its processing checks.

``queued → preparing`` (claim; the edit must still be READY with its file present, the
connection present and ``connected``) ``→ uploading`` (authorize; open the resumable
session — **persisted, encrypted, before any byte is sent**, so a crash anywhere afterwards
resumes this session instead of creating a second video; stream the short from storage in
ranged chunks through :func:`run_upload`) ``→ uploaded`` (video id recorded, session secret
deleted, the channel's name learned) and then, from countdown status checks, ``processing →
published`` — or the job stays at an honest ``uploaded`` when YouTube will not say.

- **Fencing:** every commit checks the job's attempt token; a superseded attempt stops at
  its next checkpoint without writing.
- **Retries:** a failed job keeps its session, so the retry endpoint's new attempt resumes
  it; a job with a video id is never uploaded again. An expired session (no video yet) is
  replaced once per attempt.
- **Accounts:** ``authentication_required`` (revoked or expired consent, or a token no key
  can open) marks the connection ``needs_reconnect``; a disconnected account fails the job.
"""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    ClipEdit,
    ClipEditStatus,
    ConnectionStatus,
    PublishingConnection,
    PublishJob,
    PublishStatus,
)
from app.services.performance.content import link_quietly
from app.services.publishing import connections, platforms
from app.services.publishing.factory import get_publishing_provider
from app.services.publishing.provider import (
    PublishErrorCode,
    PublishingProvider,
    PublishProviderError,
    UploadState,
    VideoRequest,
    VideoStatus,
)
from app.services.publishing.tokens import (
    EncryptedToken,
    TokenCipher,
    TokenDecryptionError,
    TokenKeyError,
)
from app.services.publishing.uploader import UploadSource, run_upload
from app.services.storage import (
    InvalidStorageKey,
    ObjectNotFound,
    StorageError,
    StorageProvider,
    media_storage,
)

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500
UNKNOWN_PROCESSING = "unknown"  # processing cannot be followed (e.g. upload-only scope)


class PipelineSuperseded(Exception):
    """The job was handed to a newer attempt, or deleted."""


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(job: PublishJob, settings: Settings, now: datetime | None = None) -> bool:
    if job.status not in (PublishStatus.PREPARING, PublishStatus.UPLOADING):
        return False
    last = job.heartbeat_at or job.started_at
    if last is None:
        return True
    return ((now or _now()) - last).total_seconds() > settings.publish_stale_after_seconds


def _session_purpose(job_id: uuid.UUID) -> str:
    return f"youtube-session-{job_id}"  # binds the stored session URI to this job


# --- the job -------------------------------------------------------------------------------


def publish_short(
    publish_job_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: StorageProvider | None = None,
    provider: PublishingProvider | None = None,
    task_id: str | None = None,
    schedule_status_check=None,
    sleep: Callable[[float], None] = time.sleep,
) -> PublishJob | None:
    """Run one attempt of a publish job. Problems are recorded on the row, never raised."""
    settings = settings or get_settings()
    storage = storage or media_storage(settings)
    job = db.get(PublishJob, publish_job_id)
    if job is None:
        logger.warning("Publish job %s no longer exists; nothing to do", publish_job_id)
        return None
    if not _claim(job, db, settings, task_id):
        return job

    def fail(code: str, message: str, status: PublishStatus = PublishStatus.FAILED) -> None:
        try:
            _fail(job, publish_job_id, db, code, message, status, task_id=task_id)
        except Exception:
            logger.exception("Could not record the failure of publish job %s", publish_job_id)
            db.rollback()

    try:
        _execute(job, db, settings, storage, provider, task_id, sleep)
    except PipelineSuperseded:
        logger.info("Publish job %s was taken over or removed; stopping", publish_job_id)
        return job
    except PipelineFailure as failure:
        fail(failure.code, failure.message)
        return job
    except PublishProviderError as error:
        if error.code == PublishErrorCode.AUTHENTICATION_REQUIRED:
            _needs_reconnect(job, db)
        status = (
            PublishStatus.PROVIDER_FAILED
            if error.code == PublishErrorCode.PROCESSING_FAILED
            else PublishStatus.FAILED
        )
        fail(error.code.value, error.message, status)
        return job
    except (StorageError, OSError):
        logger.exception("Storage failure while publishing %s", publish_job_id)
        fail("storage_failure", "The short could not be read from storage; retry")
        return job
    except SoftTimeLimitExceeded:
        fail("time_limit", "Publishing ran longer than the worker allows; retry to resume")
        return job
    except Exception:
        logger.exception("Unexpected error publishing %s", publish_job_id)
        fail("internal_error", "Unexpected error while publishing; retry")
        return job

    if schedule_status_check is not None:
        schedule_status_check(job.id, settings.publish_status_poll_seconds)
    return job


def _claim(job: PublishJob, db: Session, settings: Settings, task_id: str | None) -> bool:
    if task_id and job.celery_task_id and job.celery_task_id != task_id:
        logger.info("Publish job %s belongs to a newer attempt; ignoring", job.id)
        return False
    if job.status != PublishStatus.QUEUED and not is_stale(job, settings):
        logger.info("Publish job %s is %s; nothing to start", job.id, job.status)
        return False
    now = _now()
    job.status = PublishStatus.PREPARING
    job.started_at = job.heartbeat_at = now
    job.completed_at = None
    job.error_code = job.error_message = None
    db.commit()
    return True


def _execute(
    job: PublishJob,
    db: Session,
    settings: Settings,
    storage: StorageProvider,
    provider: PublishingProvider | None,
    task_id: str | None,
    sleep: Callable[[float], None],
) -> None:
    if job.provider_video_id:  # already on YouTube: never upload it twice
        _mark_uploaded(job, db, task_id, job.provider_video_id, None, None)
        return
    edit = db.get(ClipEdit, job.edit_id)
    if edit is None or edit.status != ClipEditStatus.READY or not edit.storage_key:
        raise PipelineFailure("edit_not_ready", "The short is no longer ready to publish")
    try:
        size = storage.size(edit.storage_key)
    except (ObjectNotFound, InvalidStorageKey):
        raise PipelineFailure(
            "edit_missing", "The short's file is missing; render it again"
        ) from None
    if size <= 0:
        raise PipelineFailure("edit_missing", "The short's file is empty; render it again")
    connection = db.get(PublishingConnection, job.connection_id) if job.connection_id else None
    if connection is None:
        raise PipelineFailure("not_connected", "Connect your account again and retry")
    if connection.status != ConnectionStatus.CONNECTED:
        raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED)

    try:
        cipher = TokenCipher.from_settings(settings)
        refresh_token = connections.refresh_token_of(db, cipher, connection)
    except (TokenKeyError, TokenDecryptionError):
        raise PublishProviderError(PublishErrorCode.AUTHENTICATION_REQUIRED) from None
    provider = provider or get_publishing_provider(settings, job.provider)
    auth = provider.authorize(refresh_token)
    if auth.rotated_refresh_token:
        # The old token is already dead: keep the new one before anything else can fail.
        connections.store_rotated_token(db, cipher, connection, auth.rotated_refresh_token)

    job.bytes_total = size
    job.status = PublishStatus.UPLOADING
    _heartbeat(job, db, task_id)

    request = VideoRequest(
        title=job.title,
        description=job.description,
        tags=tuple(job.tags or ()),
        privacy=job.privacy,
        made_for_kids=job.made_for_kids,
        category_id=job.category_id,
        size_bytes=size,
        content_type=edit.content_type or "video/mp4",
        options=dict(job.options or {}),
    )
    key = edit.storage_key

    def read(offset: int, length: int) -> bytes:
        return b"".join(storage.iter_range(key, offset, offset + length - 1))

    def on_progress(confirmed: int) -> None:
        job.bytes_uploaded = max(job.bytes_uploaded or 0, confirmed)
        job.progress_percent = max(job.progress_percent, int(99 * confirmed / size))
        _heartbeat(job, db, task_id)

    restarted = False
    while True:
        session_uri = _session(job, db, cipher, provider, auth, request, task_id)
        try:
            result = run_upload(
                provider, auth, session_uri, UploadSource(size, read),
                chunk_bytes=settings.youtube_upload_chunk_bytes, on_progress=on_progress,
                still_owner=lambda: _ensure_still_owner(job, db, task_id), sleep=sleep,
            )  # fmt: skip
            break
        except PublishProviderError as error:
            if error.code != PublishErrorCode.UPLOAD_SESSION_EXPIRED or restarted:
                raise
            # The session vanished before completing (no video exists): open a new one once.
            restarted = True
            logger.info("Publish job %s: upload session expired; starting a new one", job.id)
            job.upload_session_ciphertext = job.upload_session_key_version = None
            job.bytes_uploaded, job.progress_percent = 0, 0
            _heartbeat(job, db, task_id)

    _mark_uploaded(job, db, task_id, result.video_id, result.channel_id, result.channel_title)
    connection.last_used_at = _now()
    if result.channel_title and not connection.account_title:
        connection.account_id = (result.channel_id or "")[:128]
        connection.account_title = result.channel_title[:255]
    db.commit()


def _session(job, db, cipher, provider, auth, request, task_id) -> str:
    """The job's upload session: resumed when stored, otherwise opened and stored (encrypted)
    before a single byte is sent."""
    purpose = _session_purpose(job.id)
    if job.upload_session_ciphertext:
        try:
            return cipher.decrypt(
                EncryptedToken(job.upload_session_ciphertext, job.upload_session_key_version),
                user_id=job.user_id,
                provider=purpose,
            )
        except TokenDecryptionError:
            logger.warning("Publish job %s: stored session unreadable; opening a new one", job.id)
    _ensure_still_owner(job, db, task_id)
    uri = provider.start_upload(auth, request)
    sealed = cipher.encrypt(uri, user_id=job.user_id, provider=purpose)
    job.upload_session_ciphertext = sealed.ciphertext
    job.upload_session_key_version = sealed.key_version
    job.upload_session_started_at = _now()
    _heartbeat(job, db, task_id)
    return uri


def _mark_uploaded(job, db, task_id, video_id, channel_id, channel_title) -> None:
    _ensure_still_owner(job, db, task_id)
    job.provider_video_id = video_id
    job.provider_upload_status = UploadState.UPLOADED.value
    job.status = PublishStatus.UPLOADED
    job.progress_percent = 100
    job.bytes_uploaded = job.bytes_total or job.bytes_uploaded
    job.upload_session_ciphertext = job.upload_session_key_version = None  # secret not needed
    job.completed_at = _now()
    job.heartbeat_at = job.completed_at
    db.commit()
    logger.info("Publish job %s uploaded to %s", job.id, job.provider)
    # Performance analytics: remember which PeakSift output became this remote video.
    link_quietly(db, job)


# --- processing checks ---------------------------------------------------------------------


def check_status(
    publish_job_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    provider: PublishingProvider | None = None,
    schedule_status_check=None,
) -> PublishJob | None:
    """Ask the provider how processing is going; reschedule while it is still processing."""
    settings = settings or get_settings()
    job = db.get(PublishJob, publish_job_id)
    if job is None or job.status not in (PublishStatus.UPLOADED, PublishStatus.PROCESSING):
        return job
    if not job.provider_video_id or job.status_checks >= settings.publish_status_max_polls:
        return job
    connection = db.get(PublishingConnection, job.connection_id) if job.connection_id else None
    if connection is None or connection.status != ConnectionStatus.CONNECTED:
        return _processing_unknown(job, db)  # stays honestly "uploaded"
    job.status_checks += 1
    db.commit()
    try:
        cipher = TokenCipher.from_settings(settings)
        provider = provider or get_publishing_provider(settings, job.provider)
        auth = provider.authorize(connections.refresh_token_of(db, cipher, connection))
        if auth.rotated_refresh_token:
            connections.store_rotated_token(db, cipher, connection, auth.rotated_refresh_token)
        status = provider.video_status(auth, job.provider_video_id)
    except (PublishProviderError, TokenDecryptionError, TokenKeyError) as error:
        logger.info("Publish job %s: status unavailable (%s)", job.id, type(error).__name__)
        status = None
    after = getattr(provider, "publishes_after_processing", False)
    if status is None and after:
        # The post only exists once PeakSift publishes it: keep checking (bounded below).
        status = VideoStatus(UploadState.UPLOADED)
    if status is None or status.upload == UploadState.UNKNOWN:
        return _processing_unknown(job, db)  # YouTube will not say: the job ends at "uploaded"
    job.provider_upload_status = status.upload.value
    if status.upload == UploadState.PROCESSED:
        job.status = PublishStatus.PUBLISHED
        job.published_at = _now()
    elif status.upload in (UploadState.FAILED, UploadState.REJECTED, UploadState.DELETED):
        job.status = PublishStatus.PROVIDER_FAILED
        job.error_code = PublishErrorCode.PROCESSING_FAILED.value
        name = platforms.label(job.provider)
        job.error_message = {
            UploadState.REJECTED: f"{name} rejected this video",
            UploadState.DELETED: f"The video was removed from {name}",
        }.get(status.upload, f"{name} could not process this video")
        if status.reason:
            job.provider_processing_status = status.reason[:32]
    else:
        job.status = PublishStatus.PROCESSING
        if after and job.status_checks >= settings.publish_status_max_polls:
            # Never leave it looking posted: it is not on the platform until published.
            name = platforms.label(job.provider)
            job.status = PublishStatus.PROVIDER_FAILED
            job.error_code = PublishErrorCode.PROCESSING_FAILED.value
            job.error_message = (
                f"{name} was still processing the video when PeakSift stopped checking, so it "
                "was not posted. Post it again."
            )
    db.commit()
    if job.status == PublishStatus.PROCESSING and schedule_status_check is not None:
        if job.status_checks < settings.publish_status_max_polls:
            schedule_status_check(job.id, settings.publish_status_poll_seconds)
    return job


def _processing_unknown(job: PublishJob, db: Session) -> PublishJob:
    """Record that processing cannot be followed, so nobody waits for an answer."""
    job.provider_processing_status = UNKNOWN_PROCESSING
    db.commit()
    return job


def awaiting_processing(job: PublishJob, settings: Settings) -> bool:
    """Whether a processing check is still due (the UI keeps following until it is not)."""
    if job.status == PublishStatus.PROCESSING:
        return job.status_checks < settings.publish_status_max_polls
    return (
        job.status == PublishStatus.UPLOADED
        and job.provider_processing_status != UNKNOWN_PROCESSING
        and job.status_checks < settings.publish_status_max_polls
    )


# --- state helpers -------------------------------------------------------------------------


def _key(job: PublishJob) -> uuid.UUID:
    from sqlalchemy import inspect

    return inspect(job).identity[0]


def _still_owner(job: PublishJob, db: Session, task_id: str | None) -> bool:
    if task_id is None:
        return True
    row = db.execute(select(PublishJob.celery_task_id).where(PublishJob.id == _key(job))).first()
    return row is not None and (not row.celery_task_id or row.celery_task_id == task_id)


def _ensure_still_owner(job: PublishJob, db: Session, task_id: str | None) -> None:
    if not _still_owner(job, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(job: PublishJob, db: Session, task_id: str | None) -> None:
    _ensure_still_owner(job, db, task_id)
    job.heartbeat_at = _now()
    db.commit()


def _needs_reconnect(job: PublishJob, db: Session) -> None:
    db.rollback()
    connection = db.get(PublishingConnection, job.connection_id) if job.connection_id else None
    if connection is not None and connection.status != ConnectionStatus.NEEDS_RECONNECT:
        connections.mark_needs_reconnect(db, connection)


def _fail(job, job_id, db, code, message, status, *, task_id) -> None:
    db.rollback()
    if not _still_owner(job, db, task_id):
        logger.info("Publish job %s failed (%s) after a takeover; left alone", job_id, code)
        return
    job.status = status
    job.error_code = code[:64]
    job.error_message = message[:MAX_ERROR_LENGTH]
    job.completed_at = _now()
    job.heartbeat_at = job.completed_at
    db.commit()
    logger.warning("Publish job %s failed: %s", job_id, code)


__all__ = ["awaiting_processing", "check_status", "is_stale", "publish_short"]
