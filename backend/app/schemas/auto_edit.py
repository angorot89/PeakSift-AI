"""Auto Edit requests and responses. Responses never carry prompts, model output, provider
internals, model server addresses, task ids, fingerprints, storage keys or paths."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.auto_edit import AutoEditRecipe
from app.schemas.clip_edit import ClipEditRead


class AutoEditCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The recipe; optional when a template is given (its starting style, else Clean).
    recipe: AutoEditRecipe | None = None
    # V1.7: one of the creator's Short templates (with its brand); applied after planning.
    template_id: uuid.UUID | None = None
    # Optional: one of this project's music tracks, chosen by the creator for this plan.
    # Auto Edit never picks music on its own.
    music_asset_id: uuid.UUID | None = None
    # V1.4: let the planner consider patterns from the creator's own published shorts
    # (weak hints inside the recipe's bounds). Off unless the creator turns it on.
    use_performance_context: bool = False

    @model_validator(mode="after")
    def _recipe_or_template(self) -> "AutoEditCreate":
        if self.recipe is None and self.template_id is None:
            raise ValueError("Choose a recipe or a template")
        return self


class AutoEditRecipeRead(BaseModel):
    name: AutoEditRecipe
    version: str
    label: str
    description: str


class AutoEditConfidence(BaseModel):
    """What the plan was based on, in plain values (never a score)."""

    planner: Literal["local_ai", "rules"]
    fallback: bool  # the rules stood in for the local model
    framing: Literal["high", "mixed", "fallback"] | None
    word_timing: bool
    phrase_timing: bool
    broll_method: Literal["local_ai", "keyword", "keyword_fallback"] | None
    broll_suggestions: int
    matched_assets: int


class AutoEditPlanRead(BaseModel):
    id: uuid.UUID
    clip_id: uuid.UUID
    status: str
    progress_percent: int
    attempt: int
    is_stale: bool
    generation: int
    recipe: AutoEditRecipe
    recipe_version: str
    recipe_label: str
    music_asset_id: uuid.UUID | None
    # Once ready: a normal edit configuration (the same snapshot an edit stores), creator-
    # facing explanations per section with notes, and what the plan was based on.
    configuration: dict[str, Any] | None
    explanations: dict[str, Any] | None
    confidence: AutoEditConfidence | None
    clip_edit_id: uuid.UUID | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    applied_at: datetime | None
    # The patterns from the creator's shorts this plan was given (product copy), when used.
    performance_hints: list[str] | None = None


class PerformanceContextRead(BaseModel):
    """Whether patterns from the creator's own shorts can inform Auto Edit right now."""

    available: bool
    simulated: bool
    sample_size: int
    hints: list[str]


class AutoEditPlanPage(BaseModel):
    plans: list[AutoEditPlanRead]


class AutoEditApplyRead(BaseModel):
    plan: AutoEditPlanRead
    edit: ClipEditRead
