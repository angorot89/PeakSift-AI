"""Choosing the Auto Edit planner. The planner is server configuration — never a client choice.

``AUTO_EDIT_PLANNER_PROVIDER`` names it; ``AUTO_EDIT_OLLAMA_MODEL`` (empty: the first
``OLLAMA_CLIP_MODELS`` entry) is the local model. Nothing is constructed at import time.
"""

from app.core.config import Settings
from app.services.auto_edit.contract import AutoEditPlanner, PlannerConfigurationError


def planner_model(settings: Settings) -> str:
    """The configured local model, or the first allowed clip-detection model."""
    configured = settings.auto_edit_ollama_model.strip()
    if configured:
        return configured
    allowed = [m.strip() for m in settings.ollama_clip_models.split(",") if m.strip()]
    return allowed[0] if allowed else ""


def get_planner(settings: Settings, name: str, model: str) -> AutoEditPlanner:
    if name == "ollama":
        if not model:
            raise PlannerConfigurationError("No local model is configured for Auto Edit")
        from app.services.auto_edit.ollama import OllamaAutoEditPlanner  # lazy: no client at import

        return OllamaAutoEditPlanner(settings, model)
    raise PlannerConfigurationError("The Auto Edit planner is not supported")
