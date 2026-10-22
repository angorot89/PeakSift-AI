"""Performance analytics tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.performance.lifecycle import schedule_due
from app.services.performance.sync import run_sync
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.sync_performance", bind=True)
def sync_performance_task(self, sync_id: str) -> None:
    """Run one ``AnalyticsSync``. No Celery-level autoretry: failures are recorded on the row
    and the video's next sync is scheduled with a backoff."""
    try:
        sync_uuid = uuid.UUID(sync_id)
    except ValueError:
        logger.error("sync_performance received an invalid id %r", sync_id)
        return
    with SessionLocal() as db:
        run_sync(sync_uuid, db, task_id=self.request.id)


@celery_app.task(name="peaksift.schedule_performance_syncs")
def schedule_performance_syncs_task() -> None:
    """Celery beat: start the syncs that are due (a bounded batch per run)."""
    with SessionLocal() as db:
        schedule_due(db, get_settings())
