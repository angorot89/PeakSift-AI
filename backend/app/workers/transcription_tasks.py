"""Transcription tasks. Only database ids travel through the broker — never model
objects, file handles, media bytes or secrets."""

import logging
import uuid

from app.core.database import SessionLocal
from app.models import TranscriptionStatus
from app.services.transcription.pipeline import run_transcription
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def start_default_detection(db, video) -> None:
    """Quick start's follow-up. Imported here, not at the top: the job dispatcher imports this
    module, and the follow-up needs the dispatcher."""
    from app.services.clip_detection.autostart import start_default_detection as start

    start(db, video)


@celery_app.task(name="peaksift.ping", ignore_result=False)
def ping() -> str:
    """Round-trip check used to verify a real broker + worker setup."""
    return "pong"


@celery_app.task(name="peaksift.transcribe_video", bind=True)
def transcribe_video(self, transcription_id: str) -> None:
    """Run the transcription pipeline for a `Transcription` row.

    No Celery-level autoretry: transient provider errors are retried inside the
    pipeline with bounded backoff, and every other failure is recorded on the row
    (status `failed`) rather than re-queued, so a broken file can never loop forever.
    The worker opens and closes its own database session.
    """
    try:
        transcription_uuid = uuid.UUID(transcription_id)
    except ValueError:
        logger.error("transcribe_video received an invalid id %r", transcription_id)
        return
    with SessionLocal() as db:
        transcription = run_transcription(transcription_uuid, db, task_id=self.request.id)
        if (
            transcription is not None
            and transcription.auto_find_moments
            and transcription.status == TranscriptionStatus.COMPLETED
        ):
            # Quick start: the creator asked for moments in the same step. A problem here
            # must never turn a finished transcript into a failed task.
            try:
                start_default_detection(db, transcription.video)
            except Exception:
                db.rollback()
                logger.exception("Quick start could not begin moment detection")
