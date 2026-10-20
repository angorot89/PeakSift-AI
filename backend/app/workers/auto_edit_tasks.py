"""Auto Edit planning tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.auto_edit.pipeline import run_auto_edit_plan
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.plan_auto_edit", bind=True)
def plan_auto_edit_task(self, plan_id: str) -> None:
    """Plan one ``AutoEditPlan`` row. No Celery-level autoretry: failures are recorded on the
    row and retried explicitly."""
    try:
        plan_uuid = uuid.UUID(plan_id)
    except ValueError:
        logger.error("plan_auto_edit received an invalid id %r", plan_id)
        return
    with SessionLocal() as db:
        run_auto_edit_plan(plan_uuid, db, task_id=self.request.id)
