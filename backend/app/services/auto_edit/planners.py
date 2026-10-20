"""Choosing the Auto Edit planner, and falling back honestly when it cannot answer.

The planner is server configuration — never a client choice: ``AUTO_EDIT_PLANNER_PROVIDER``
is ``ollama`` (a local model; ``AUTO_EDIT_OLLAMA_MODEL``, empty = the first
``OLLAMA_CLIP_MODELS`` entry) or ``fallback`` (the deterministic rules only).

When the model cannot answer — unreachable, timed out, not installed, malformed even after
its one corrective attempt — and ``AUTO_EDIT_FALLBACK_ENABLED`` is on, the deterministic
planner stands in and the outcome says why (``fallback_reason``), so the plan is labelled
accordingly. A configuration mistake (no model configured) is never hidden by the fallback.
Nothing is constructed at import time.
"""

import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.services.auto_edit.contract import (
    AutoEditContext,
    AutoEditPlanner,
    PlannerConfigurationError,
    PlannerError,
    PlannerResult,
)
from app.services.auto_edit.fallback import (
    FALLBACK_MODEL,
    FALLBACK_PROVIDER,
    FallbackAutoEditPlanner,
)

logger = logging.getLogger(__name__)


def planner_model(settings: Settings) -> str:
    """The configured local model, or the first allowed clip-detection model."""
    if settings.auto_edit_planner_provider == FALLBACK_PROVIDER:
        return FALLBACK_MODEL
    configured = settings.auto_edit_ollama_model.strip()
    if configured:
        return configured
    allowed = [m.strip() for m in settings.ollama_clip_models.split(",") if m.strip()]
    return allowed[0] if allowed else ""


def get_planner(settings: Settings, name: str, model: str) -> AutoEditPlanner:
    if name == FALLBACK_PROVIDER:
        return FallbackAutoEditPlanner()
    if name == "ollama":
        if not model:
            raise PlannerConfigurationError("No local model is configured for Auto Edit")
        from app.services.auto_edit.ollama import OllamaAutoEditPlanner  # lazy: no client at import

        return OllamaAutoEditPlanner(settings, model)
    raise PlannerConfigurationError("The Auto Edit planner is not supported")


@dataclass(frozen=True)
class PlanOutcome:
    result: PlannerResult
    fallback_reason: str | None = None  # why the deterministic planner stood in


def plan(
    context: AutoEditContext, planner: AutoEditPlanner, *, fallback_enabled: bool
) -> PlanOutcome:
    """Ask the planner; let the deterministic planner stand in when it cannot answer."""
    if planner.name == FALLBACK_PROVIDER:
        return PlanOutcome(planner.plan(context))
    try:
        return PlanOutcome(planner.plan(context))
    except PlannerError as error:
        if not (fallback_enabled and error.fallback_ok):
            raise
        logger.warning("Auto Edit planner unavailable (%s); using the fallback rules", error.code)
        return PlanOutcome(FallbackAutoEditPlanner().plan(context), fallback_reason=error.code)
