"""The Auto Edit planning job: what PeakSift knows → planner → server validation → a ready plan.

Runs in a Celery worker (``peaksift.plan_auto_edit``; only the plan id crosses the broker). The
``auto_edit_plans`` row is the source of truth and is only changed through ``state``:

- **Claiming and ownership:** see ``state`` — a finished plan is never re-run, a live one not
  twice, a stale one is taken over, and a worker whose attempt was superseded (a retry) or
  whose plan was deleted (its clip was removed) never writes again.
- **Stages (honest, not percentages of work):** analyzing (gathering completed analyses and
  assets, ``sources``), planning (the configured planner — the local model is bounded by
  ``AUTO_EDIT_TIMEOUT_SECONDS`` with one corrective attempt — or the deterministic rules,
  which also stand in when the model cannot answer), validating (``validate_plan``), ready.
- **Systemic invalid output:** if a model's proposal cannot form any valid configuration, the
  deterministic plan is validated instead and the plan says so (``fallback_reason``
  ``plan_invalid``); only if that also fails is the plan failed.
- **Transactional result:** configuration, explanations, confidence summary and ``ready`` are
  written in one commit.

The plan never starts other jobs and never renders: applying it (the API) creates a normal edit.
"""

import logging
import uuid

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AutoEditPlan, AutoEditStatus
from app.services import markets
from app.services.auto_edit import state
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.contract import AutoEditPlanner, PlannerError
from app.services.auto_edit.fallback import FALLBACK_PROVIDER, FallbackAutoEditPlanner
from app.services.auto_edit.planners import get_planner, plan
from app.services.auto_edit.recipes import recipe_version
from app.services.auto_edit.sources import Gathered, SourcesUnavailable, gather
from app.services.auto_edit.template import apply_template
from app.services.auto_edit.validation import PlanRejected, ValidatedPlan, validate_plan
from app.services.storage import StorageProvider, StorageUnavailable, media_storage

logger = logging.getLogger(__name__)


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def run_auto_edit_plan(
    plan_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    planner: AutoEditPlanner | None = None,
    storage: StorageProvider | None = None,
    task_id: str | None = None,
) -> AutoEditPlan | None:
    """Plan one ``AutoEditPlan`` row. Problems are recorded, never raised."""
    settings = settings or get_settings()
    row = db.get(AutoEditPlan, plan_id)
    if row is None:
        logger.warning("Auto Edit plan %s no longer exists; nothing to do", plan_id)
        return None
    if not state.claim(row, db, settings, task_id):
        return row

    def fail(code: str, message: str) -> None:
        try:
            state.fail(row, db, code, message, task_id=task_id)
        except Exception:
            # The database itself is failing: leave the row to go stale; retry recovers it.
            logger.exception("Could not record the failure of Auto Edit plan %s", plan_id)
            db.rollback()

    try:
        _execute(row, db, settings, planner, storage or media_storage(settings), task_id)
    except state.PlanSuperseded:
        logger.info("Auto Edit plan %s was taken over or removed; stopping", plan_id)
    except (PipelineFailure, SourcesUnavailable, PlannerError, PlanRejected) as error:
        fail(error.code, error.message)
    except StorageUnavailable:
        fail("storage_unavailable", "Media storage is unavailable; retry in a moment")
    except SoftTimeLimitExceeded:
        fail("time_limit", "Planning ran longer than the worker allows; retry it")
    except Exception:
        logger.exception("Unexpected error planning Auto Edit plan %s", plan_id)
        fail("internal_error", "Unexpected error while planning the edit")
    return row


def _execute(
    row: AutoEditPlan,
    db: Session,
    settings: Settings,
    planner: AutoEditPlanner | None,
    storage: StorageProvider,
    task_id: str | None,
) -> None:
    try:
        request = AutoEditRequest.from_snapshot(row.config)  # the stored snapshot
        recipe = recipe_version(request.recipe_version)
    except ValueError:
        raise PipelineFailure(
            "config_invalid", "This Auto Edit plan's configuration is not supported"
        ) from None
    clip = row.clip
    gathered = gather(clip, db, settings, storage, request)
    state.advance(row, db, AutoEditStatus.PLANNING, task_id)

    chosen = planner or get_planner(settings, request.provider, request.model)
    outcome = plan(gathered.context, chosen, fallback_enabled=request.fallback_enabled)
    state.advance(row, db, AutoEditStatus.VALIDATING, task_id)

    result, fallback_reason = outcome.result, outcome.fallback_reason
    try:
        validated = validate_plan(result.proposal, gathered.context, recipe)
    except PlanRejected:
        if result.provider == FALLBACK_PROVIDER or not request.fallback_enabled:
            raise
        logger.warning("Auto Edit plan %s: the model's plan was invalid; using the rules", row.id)
        result = FallbackAutoEditPlanner().plan(gathered.context)
        fallback_reason = "plan_invalid"
        validated = validate_plan(result.proposal, gathered.context, recipe)

    if request.template is not None:
        # The template (and its brand) win over the planner and the recipe: applied last.
        validated = apply_template(validated, request.template, gathered.context)
    explanations = _with_context_notes(validated, gathered)
    state.finish(
        row,
        db,
        configuration=validated.configuration.snapshot(),
        configuration_fingerprint=validated.configuration.fingerprint(),
        explanations=explanations,
        confidence=_confidence(gathered, result.provider, fallback_reason, validated),
        provider=result.provider,
        model=result.model,
        fallback_reason=fallback_reason,
        task_id=task_id,
    )
    logger.info(
        "Auto Edit plan %s ready: recipe %s by %s%s (%d unknown handles, %d notes)",
        row.id,
        recipe.version,
        result.provider,
        f" (fallback: {fallback_reason})" if fallback_reason else "",
        validated.report.unknown_handles,
        len(validated.report.degraded),
    )


def _with_context_notes(validated: ValidatedPlan, gathered: Gathered) -> dict:
    explanations = dict(validated.explanations)
    notes = list(explanations.get("notes", []))
    if gathered.music_missing:
        notes.insert(0, "The music you chose is no longer available, so no music was added.")
    if gathered.market is not None:
        explanations["market"] = gathered.market  # frozen with the plan (and its Short)
        note = market_note(validated, gathered)
        if note:
            notes.append(note)
    explanations["notes"] = notes
    explanations["used_suggestions"] = list(validated.used_suggestion_ids)
    return explanations


def market_note(validated: ValidatedPlan, gathered: Gathered) -> str | None:
    """What Morocco Mode did with the visuals, in plain words (None when nothing was placed)."""
    visuals = validated.configuration.visuals
    placed = {element.asset_id for element in visuals.elements} if visuals else set()
    if not placed:
        return None
    local = markets.market(gathered.market["code"]).local_label or gathered.market["name"]
    if placed & gathered.local_assets:
        return f"{gathered.market['name']} Mode put your {local} visuals first for this Short."
    return (
        f"No strong {local} visual matched these moments, so PeakSift used one from your "
        "Global library."
    )


def _confidence(
    gathered: Gathered, provider: str, fallback_reason: str | None, validated: ValidatedPlan
) -> dict:
    caps = gathered.context.capabilities
    return {
        "planner": "rules" if provider == FALLBACK_PROVIDER else "local_ai",
        "fallback_reason": fallback_reason,
        "framing": caps.reframe_confidence,
        "word_timing": caps.word_timing,
        "phrase_timing": caps.phrase_timing,
        "broll_method": gathered.broll_method,
        "broll_suggestions": len(gathered.context.broll),
        "matched_assets": len(gathered.context.visual_assets),
        "unknown_handles": validated.report.unknown_handles,
    }
