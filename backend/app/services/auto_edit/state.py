"""Auto Edit plan state: claiming, attempt ownership, honest progress, failure and applying.

The ``auto_edit_plans`` row is the source of truth; these helpers are the only way the planning
job and the API change it.

- **Claiming:** a ready, applied or failed plan is never re-run by a stray task; a live one
  (fresh heartbeat) is not run twice; a row whose task id belongs to a newer attempt is ignored.
- **Ownership:** the task id committed before enqueueing is the attempt token. Every commit
  and the failure path re-read it, so a stalled worker that a retry took over never writes the
  row again. A row deleted mid-run (its clip was removed) stops the job.
- **Honest progress:** stage-based (a language model exposes no real progress): 5 claimed,
  15 analyzing, 35 planning, 85 validating, 100 ready.
- **Applying:** only a ready plan can be applied; it then records the edit it became and is
  never changed again. Applying an applied plan returns it unchanged.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AutoEditPlan, AutoEditStatus
from app.models.auto_edit import ERROR_MESSAGE_MAX_LENGTH

logger = logging.getLogger(__name__)

CLAIMED_PROGRESS = 5
STAGE_PROGRESS = {
    AutoEditStatus.ANALYZING: 15,
    AutoEditStatus.PLANNING: 35,
    AutoEditStatus.VALIDATING: 85,
}
RUNNING_STATUSES = tuple(STAGE_PROGRESS)


class PlanSuperseded(Exception):
    """A newer attempt owns this plan (or the row is gone); stop without writing."""


class PlanNotReady(Exception):
    """Only a ready plan can be applied."""


def now() -> datetime:
    return datetime.now(UTC)


def is_stale(plan: AutoEditPlan, settings: Settings, *, at: datetime | None = None) -> bool:
    """A running plan whose worker stopped reporting (a retry may take it over)."""
    if plan.status not in RUNNING_STATUSES:
        return False
    last = plan.heartbeat_at or plan.started_at or plan.created_at
    return ((at or now()) - last).total_seconds() > settings.auto_edit_stale_after_seconds


def claim(plan: AutoEditPlan, db: Session, settings: Settings, task_id: str | None) -> bool:
    """Start this attempt, or say why not (False: nothing to do for this task)."""
    if task_id and plan.celery_task_id and plan.celery_task_id != task_id:
        logger.info("Auto Edit plan %s belongs to a newer attempt; ignoring", plan.id)
        return False
    if plan.status in (AutoEditStatus.READY, AutoEditStatus.APPLIED):
        logger.info("Auto Edit plan %s is already finished; ignoring duplicate task", plan.id)
        return False
    if plan.status == AutoEditStatus.FAILED:
        logger.info("Auto Edit plan %s is failed; a retry must reset it first", plan.id)
        return False
    if plan.status != AutoEditStatus.QUEUED and not is_stale(plan, settings):
        logger.info("Auto Edit plan %s is already running elsewhere", plan.id)
        return False
    started = now()
    plan.status = AutoEditStatus.ANALYZING
    plan.progress_percent = CLAIMED_PROGRESS
    plan.started_at = plan.heartbeat_at = started
    plan.completed_at = None
    plan.error_code = plan.error_message = None
    plan.fallback_reason = None
    plan.configuration_snapshot = plan.configuration_fingerprint = None
    plan.explanation_snapshot = plan.confidence_summary = None
    db.commit()
    return True


def key(plan: AutoEditPlan) -> uuid.UUID:
    """The primary key without a database round trip (safe if the row was deleted)."""
    return sa_inspect(plan).identity[0]


def still_owner(plan: AutoEditPlan, db: Session, task_id: str | None) -> bool:
    with db.no_autoflush:  # read the committed token; never flush pending changes first
        row = db.execute(
            select(AutoEditPlan.celery_task_id).where(AutoEditPlan.id == key(plan))
        ).first()
    if row is None:
        return False
    if task_id is None:
        return True
    return not row.celery_task_id or row.celery_task_id == task_id


def ensure_still_owner(plan: AutoEditPlan, db: Session, task_id: str | None) -> None:
    if not still_owner(plan, db, task_id):
        db.rollback()
        raise PlanSuperseded()


def heartbeat(plan: AutoEditPlan, db: Session, task_id: str | None) -> None:
    """Commit pending progress — but only while this attempt still owns the plan."""
    ensure_still_owner(plan, db, task_id)
    plan.heartbeat_at = now()
    db.commit()


def advance(plan: AutoEditPlan, db: Session, status: AutoEditStatus, task_id: str | None) -> None:
    """Move to the next running stage with its fixed progress."""
    plan.status = status
    plan.progress_percent = STAGE_PROGRESS[status]
    heartbeat(plan, db, task_id)


def finish(
    plan: AutoEditPlan,
    db: Session,
    *,
    configuration: dict[str, Any],
    configuration_fingerprint: str,
    explanations: dict[str, Any],
    confidence: dict[str, Any],
    provider: str,
    model: str,
    fallback_reason: str | None,
    task_id: str | None,
) -> None:
    """Write the validated result and ``ready`` in one commit (owners only)."""
    ensure_still_owner(plan, db, task_id)
    plan.configuration_snapshot = configuration
    plan.configuration_fingerprint = configuration_fingerprint
    plan.explanation_snapshot = explanations
    plan.confidence_summary = confidence
    plan.planner_provider = provider[:64]
    plan.planner_model = model[:128]
    plan.fallback_reason = fallback_reason[:64] if fallback_reason else None
    plan.status = AutoEditStatus.READY
    plan.progress_percent = 100
    plan.completed_at = plan.heartbeat_at = now()
    db.commit()


def fail(plan: AutoEditPlan, db: Session, code: str, message: str, *, task_id: str | None) -> None:
    """Record a failure — unless a newer attempt took the plan over (then do nothing)."""
    db.rollback()
    plan_id = key(plan)
    if not still_owner(plan, db, task_id):
        logger.info("Auto Edit plan %s failed (%s) after being taken over; ignoring", plan_id, code)
        return
    plan.status = AutoEditStatus.FAILED
    plan.error_code = code[:64]
    plan.error_message = message[:ERROR_MESSAGE_MAX_LENGTH]
    plan.configuration_snapshot = plan.configuration_fingerprint = None
    plan.explanation_snapshot = plan.confidence_summary = None
    plan.completed_at = plan.heartbeat_at = now()
    db.commit()
    logger.warning("Auto Edit plan %s failed: %s — %s", plan_id, code, message)


def mark_applied(plan: AutoEditPlan, db: Session, clip_edit_id: uuid.UUID) -> AutoEditPlan:
    """Record the edit a ready plan became. The row is locked so two applies serialize; an
    applied plan is returned unchanged (applying twice never changes it)."""
    db.refresh(plan, with_for_update=True)
    if plan.status == AutoEditStatus.APPLIED:
        db.rollback()
        return plan
    if plan.status != AutoEditStatus.READY:
        db.rollback()
        raise PlanNotReady()
    plan.status = AutoEditStatus.APPLIED
    plan.clip_edit_id = clip_edit_id
    plan.applied_at = now()
    db.commit()
    return plan
