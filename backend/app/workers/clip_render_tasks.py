"""Clip rendering tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.clip_render.pipeline import run_clip_render
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.render_clip", bind=True)
def render_clip_task(self, clip_id: str) -> None:
    """Render one ``Clip`` row. No Celery-level autoretry: every failure is recorded on the
    row so a broken source can never loop. The worker opens and closes its own session."""
    try:
        clip_uuid = uuid.UUID(clip_id)
    except ValueError:
        logger.error("render_clip received an invalid id %r", clip_id)
        return
    with SessionLocal() as db:
        run_clip_render(clip_uuid, db, task_id=self.request.id)
