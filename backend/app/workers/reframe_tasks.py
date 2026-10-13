"""Smart-reframing analysis tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.reframe.pipeline import run_reframe_analysis
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.analyze_reframe", bind=True)
def analyze_reframe_task(self, analysis_id: str) -> None:
    """Analyse one ``ReframeAnalysis`` row. No Celery-level autoretry: failures are recorded
    on the row and retried explicitly. The worker opens and closes its own session; the face
    detector is loaded on the first frame, never when the worker starts."""
    try:
        analysis_uuid = uuid.UUID(analysis_id)
    except ValueError:
        logger.error("analyze_reframe received an invalid id %r", analysis_id)
        return
    with SessionLocal() as db:
        run_reframe_analysis(analysis_uuid, db, task_id=self.request.id)
