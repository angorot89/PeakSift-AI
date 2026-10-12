"""Transcription tasks. Only database ids travel through the broker — never model
objects, file handles, media bytes or secrets."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.transcription.pipeline import run_transcription
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.ping", ignore_result=False)
def ping() -> str:
    """Round-trip check used to verify a real broker + worker setup."""
    return "pong"


@celery_app.task(name="peaksift.transcribe_video")
def transcribe_video(transcription_id: str) -> None:
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
        run_transcription(transcription_uuid, db)
