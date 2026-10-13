"""Short-form edit rendering tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.clip_edit.pipeline import run_clip_edit
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.render_clip_edit", bind=True)
def render_clip_edit_task(self, edit_id: str) -> None:
    """Render one ``ClipEdit`` row. No Celery-level autoretry: failures are recorded on the
    row. The worker opens and closes its own session."""
    try:
        edit_uuid = uuid.UUID(edit_id)
    except ValueError:
        logger.error("render_clip_edit received an invalid id %r", edit_id)
        return
    with SessionLocal() as db:
        run_clip_edit(edit_uuid, db, task_id=self.request.id)
