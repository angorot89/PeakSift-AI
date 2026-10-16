"""Publishing tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.publishing.pipeline import check_status, publish_short
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        logger.error("publishing task received an invalid id %r", value)
        return None


def schedule_status_check(job_id: uuid.UUID, countdown: int) -> None:
    check_publish_status_task.apply_async(args=[str(job_id)], countdown=countdown, retry=False)


@celery_app.task(name="peaksift.publish_short", bind=True)
def publish_short_task(self, publish_job_id: str) -> None:
    """Upload one ``PublishJob``. No Celery autoretry: failures are recorded on the row and
    the retry endpoint resumes the same upload session."""
    if (job_id := _uuid(publish_job_id)) is None:
        return
    with SessionLocal() as db:
        publish_short(
            job_id, db, task_id=self.request.id, schedule_status_check=schedule_status_check
        )


@celery_app.task(name="peaksift.check_publish_status")
def check_publish_status_task(publish_job_id: str) -> None:
    """Ask YouTube about processing; reschedules itself while processing, bounded."""
    if (job_id := _uuid(publish_job_id)) is None:
        return
    with SessionLocal() as db:
        check_status(job_id, db, schedule_status_check=schedule_status_check)
