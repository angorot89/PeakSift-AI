"""Clip detection tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.clip_detection.pipeline import run_clip_detection
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.detect_clips", bind=True)
def detect_clips(self, run_id: str) -> None:
    """Run the clip detection pipeline for a ``ClipDetectionRun`` row.

    No Celery-level autoretry: transient provider errors are retried inside the pipeline
    with bounded backoff; every other failure is recorded on the row. The worker opens
    and closes its own database session.
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        logger.error("detect_clips received an invalid id %r", run_id)
        return
    with SessionLocal() as db:
        run_clip_detection(run_uuid, db, task_id=self.request.id)
