"""Caption-timing tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.caption_timing.pipeline import run_caption_track
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.generate_caption_track", bind=True)
def generate_caption_track_task(self, caption_track_id: str) -> None:
    """Time the words of one ``CaptionTrack`` row. No Celery-level autoretry: failures are
    recorded on the row and retried explicitly. The speech model is loaded on first use in
    the worker process, never when the worker starts."""
    try:
        track_uuid = uuid.UUID(caption_track_id)
    except ValueError:
        logger.error("generate_caption_track received an invalid id %r", caption_track_id)
        return
    with SessionLocal() as db:
        run_caption_track(track_uuid, db, task_id=self.request.id)
