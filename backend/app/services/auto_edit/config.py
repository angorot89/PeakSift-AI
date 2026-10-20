"""The Auto Edit request snapshot stored on each plan (``AutoEditPlan.config``).

Everything is server configuration except two creator choices: the recipe (an allow-listed
name, resolved to today's exact version) and, optionally, one of the project's music tracks
explicitly chosen for this plan. The planner, its model and version, and whether the
deterministic fallback may stand in come from settings. ``generation`` > 1 marks a deliberate
"try another plan". The job always runs with its stored snapshot, never with today's defaults.
"""

from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings
from app.services.auto_edit.contract import PLANNER_VERSION
from app.services.auto_edit.planners import planner_model
from app.services.auto_edit.recipes import current_recipe

REQUEST_VERSION = "auto_edit_request_v1"


@dataclass(frozen=True)
class AutoEditRequest:
    request_version: str
    planner_version: str
    provider: str
    model: str
    fallback_enabled: bool
    recipe: str
    recipe_version: str
    music_asset_id: str | None
    generation: int

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        recipe: str,
        music_asset_id: str | None = None,
        generation: int = 1,
    ) -> "AutoEditRequest":
        chosen = current_recipe(recipe)
        return cls(
            request_version=REQUEST_VERSION,
            planner_version=PLANNER_VERSION,
            provider=settings.auto_edit_planner_provider,
            model=planner_model(settings),
            fallback_enabled=bool(settings.auto_edit_fallback_enabled),
            recipe=chosen.name.value,
            recipe_version=chosen.version,
            music_asset_id=music_asset_id,
            generation=int(generation),
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "AutoEditRequest":
        if not isinstance(snapshot, dict) or snapshot.get("request_version") != REQUEST_VERSION:
            raise ValueError("Unsupported Auto Edit request version")
        fields = cls.__dataclass_fields__
        if any(name not in snapshot for name in fields):
            raise ValueError("Incomplete Auto Edit request")
        return cls(**{name: snapshot[name] for name in fields})

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)
