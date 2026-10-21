"""Semantic indexing tasks. Only database ids travel through the broker."""

import logging
import uuid

from app.core.database import SessionLocal
from app.services.semantic.indexing import run_semantic_index
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="peaksift.index_visual_asset", bind=True)
def index_visual_asset_task(self, index_id: str) -> None:
    """Index one ``VisualSemanticIndex`` row (one asset, the current model). No Celery-level
    autoretry: failures are recorded on the row and retried explicitly."""
    try:
        index_uuid = uuid.UUID(index_id)
    except ValueError:
        logger.error("index_visual_asset received an invalid id %r", index_id)
        return
    with SessionLocal() as db:
        run_semantic_index(index_uuid, db, task_id=self.request.id)
