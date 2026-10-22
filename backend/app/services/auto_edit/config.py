"""The Auto Edit request snapshot stored on each plan (``AutoEditPlan.config``).

Everything is server configuration except the creator's choices: the recipe (an allow-listed
name, resolved to today's exact version), optionally one of the project's music tracks
explicitly chosen for this plan, and (V1.4) whether to use patterns from their published shorts
— stored as the profile snapshot itself (``performance/profile.py``). A request without it has
exactly the V1.2 snapshot, so earlier fingerprints are unchanged. The planner, its model and
version, and whether the deterministic fallback may stand in come from settings.
``generation`` > 1 marks a deliberate "try another plan". The job always runs with its stored
snapshot, never with today's defaults.
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
    performance_context: dict[str, Any] | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        recipe: str,
        music_asset_id: str | None = None,
        generation: int = 1,
        performance_context: dict[str, Any] | None = None,
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
            performance_context=performance_context,
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "AutoEditRequest":
        if not isinstance(snapshot, dict) or snapshot.get("request_version") != REQUEST_VERSION:
            raise ValueError("Unsupported Auto Edit request version")
        optional = {"performance_context"}
        fields = cls.__dataclass_fields__
        if any(name not in snapshot for name in fields if name not in optional):
            raise ValueError("Incomplete Auto Edit request")
        return cls(**{name: snapshot[name] for name in fields if name in snapshot})

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self)
        if data["performance_context"] is None:  # V1.2 snapshots (and fingerprints) unchanged
            del data["performance_context"]
        return data
