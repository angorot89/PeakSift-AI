"""B-roll suggestion tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.broll.pipeline import run_broll_analysis
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.suggest_broll", bind=True)
def suggest_broll_task(self, analysis_id: str) -> None:
    """Suggest B-roll for one ``BrollAnalysis`` row. No Celery-level autoretry: failures are
    recorded on the row and retried explicitly."""
    try:
        analysis_uuid = uuid.UUID(analysis_id)
    except ValueError:
        logger.error("suggest_broll received an invalid id %r", analysis_id)
        return
    with SessionLocal() as db:
        run_broll_analysis(analysis_uuid, db, task_id=self.request.id)
