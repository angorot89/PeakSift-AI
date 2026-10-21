"""Starting semantic indexing from the asset lifecycle, and the state the API reports.

``start_indexing`` is what an upload (and a retry, and the operator's reindex command) calls:
it requests the index (``indexing.request_index``: idempotent, fenced) and enqueues the job.
It never blocks on the model and never fails the caller: if the broker is unreachable, the
index is recorded as a retryable failure and the asset is still returned, usable by hand.

``start_lazy_indexing`` is the lazy migration after a model change: listing a library
re-queues a bounded number of stale or never-indexed assets.

``visual_search_status`` turns an asset's index rows into what a creator needs: a state
(``semantic_state``), real progress for videos (embeddings computed of frames selected), and a
safe message when it failed — never a model name, a path or an error trace.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import VisualAsset, VisualSemanticIndex
from app.services.semantic.indexing import (
    TooManyAttempts,
    mark_enqueue_failed,
    request_index,
)
from app.services.semantic.registry import configured_identity
from app.services.semantic.state import SemanticState, current_index, semantic_state

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualSearchStatus:
    state: SemanticState
    frames_done: int | None = None
    frames_total: int | None = None
    message: str | None = None
    can_retry: bool = False


def start_indexing(
    db: Session, asset: VisualAsset, settings: Settings, *, retry: bool = False
) -> VisualSemanticIndex | None:
    """Request and enqueue the asset's index by the current model (no-op when nothing to do).
    Raises TooManyAttempts for a retry beyond the budget; never raises for the broker."""
    from app.workers.dispatch import JobQueueUnavailable, enqueue_semantic_index

    index = request_index(db, asset, settings, retry=retry)
    if index is None:
        return None
    try:
        enqueue_semantic_index(index.id, task_id=index.celery_task_id)
    except JobQueueUnavailable:
        logger.warning("Semantic index %s could not be enqueued (broker unavailable)", index.id)
        mark_enqueue_failed(db, index)
    return index


def start_indexing_quietly(db: Session, asset: VisualAsset, settings: Settings) -> None:
    """For the upload path: indexing is a bonus, never a reason for the upload to fail."""
    try:
        start_indexing(db, asset, settings)
    except TooManyAttempts:
        pass
    except Exception:
        logger.exception("Could not start semantic indexing for visual asset %s", asset.id)
        db.rollback()


def start_lazy_indexing(db: Session, assets: Iterable[VisualAsset], settings: Settings) -> int:
    """After a model change (or for assets uploaded while visual search was off), listing a
    library re-queues at most ``SEMANTIC_LAZY_REINDEX_PER_REQUEST`` stale or never-indexed
    assets — bounded work per request, never failed ones (those wait for a retry), never a
    second job for an asset already queued. Returns how many were started."""
    budget = settings.semantic_lazy_reindex_per_request
    identity = configured_identity(settings)
    if not budget or identity is None:
        return 0
    started = 0
    for asset in assets:
        if started >= budget:
            break
        state = semantic_state(asset.semantic_indexes, identity)
        if state not in (SemanticState.STALE, SemanticState.NOT_INDEXED):
            continue
        try:
            if start_indexing(db, asset, settings) is not None:
                started += 1
                db.expire(asset, ["semantic_indexes"])
        except Exception:
            logger.exception("Could not re-queue visual asset %s for visual search", asset.id)
            db.rollback()
    return started


def visual_search_status(asset: VisualAsset, settings: Settings) -> VisualSearchStatus:
    identity = configured_identity(settings)
    indexes = list(asset.semantic_indexes)
    state = semantic_state(indexes, identity)
    index = current_index(indexes, identity)
    if state == SemanticState.INDEXING and index is not None:
        return VisualSearchStatus(state, index.frames_done, index.frames_total)
    if state == SemanticState.FAILED and index is not None:
        can_retry = index.attempt < settings.semantic_max_attempts
        return VisualSearchStatus(state, message=index.error_message, can_retry=can_retry)
    return VisualSearchStatus(state)
