"""What a Short template says: the creator's preferences for how a Short is edited.

A template is **preferences**, not a finished edit. Each setting either names a value the
existing editor and renderer already accept — the same enums (``Layout``, ``DynamicPreset``,
``CaptionPosition``, ``HookStyle``, ``HookPosition``, ``MusicLevel``, ``DuckingStrength``) —
or is ``None``, meaning "let the recipe decide". Nothing here is a filter, a path, an id of a
media file or a free number outside the editor's own bounds.

- **Framing**: ``smart_reframe`` is a *preference* — used only when a completed framing
  analysis exists; otherwise the Short falls back to Auto Edit's own choice (never a failure).
- **Captions**: on or off, a dynamic preset and a position (``None`` = the recipe's).
- **Opening hook**: on or off, its style, position and seconds on screen. Its words always
  come from the clip (grounded by Auto Edit), never from the template.
- **Visuals**: how much B-roll — ``none``, ``light`` (at most one) or ``recipe`` (the recipe's
  own limit). Which visuals still comes from the project's own assets.
- **Sound**: the music level and ducking used *when the creator picks music* for a Short
  (templates never pick music), whether sound effects may be added, and loudness
  normalization.
- **Brand use**: whether the brand's logo is shown and whether an end card is appended (and
  for how long). The look itself comes from the brand.

``TemplateConfig.create`` validates and normalizes (equal settings, equal snapshot); the
snapshot carries ``TEMPLATE_CONFIG_VERSION`` so a later format can still read old templates.
"""

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from app.services.audio_mix.config import DuckingStrength
from app.services.auto_edit.recipes import MusicLevel, Recipe
from app.services.clip_edit.config import CaptionPosition, DynamicPreset
from app.services.clip_edit.hook import MAX_HOOK_SECONDS, MIN_HOOK_SECONDS, HookPosition, HookStyle

TEMPLATE_CONFIG_VERSION = "template_v1"
END_CARD_SECONDS = (1.0, 3.0)
DEFAULT_END_CARD_SECONDS = 2.0


class Framing(StrEnum):
    AUTO = "auto"  # Auto Edit decides (Smart Reframe when the recipe's confidence allows)
    SMART_REFRAME = "smart_reframe"  # preferred whenever a completed analysis exists
    BLUR_BACKGROUND = "blur_background"
    CENTER_CROP = "center_crop"
    FIT = "fit"


class BrollAmount(StrEnum):
    NONE = "none"
    LIGHT = "light"  # at most one visual
    RECIPE = "recipe"  # the recipe's own limit


def _enum(kind: type[StrEnum], value: object, name: str) -> Any:
    if value is None:
        return None
    try:
        return kind(value)
    except ValueError:
        raise ValueError(f"Unsupported {name}") from None


def _bool(value: object, name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def _seconds(value: object, bounds: tuple[float, float], name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a number of seconds")
    low, high = bounds
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g} seconds")
    return round(float(value), 1)


@dataclass(frozen=True)
class TemplateConfig:
    framing: Framing = Framing.AUTO
    captions: bool = True
    caption_preset: DynamicPreset | None = None
    caption_position: CaptionPosition | None = None
    hook: bool = True
    hook_style: HookStyle | None = None
    hook_position: HookPosition | None = None
    hook_seconds: float | None = None
    broll: BrollAmount = BrollAmount.RECIPE
    music_level: MusicLevel | None = None
    ducking: DuckingStrength | None = None
    sound_effects: bool = True  # only where the recipe allows them and a matching asset exists
    normalize_loudness: bool = True
    logo: bool = True  # shown when the brand has a logo
    end_card: bool = False
    end_card_seconds: float | None = None

    @classmethod
    def create(cls, data: dict[str, Any] | None) -> "TemplateConfig":
        """Validate and normalize (ValueError with a creator-facing message otherwise)."""
        data = dict(data or {})
        unknown = set(data) - set(cls.__dataclass_fields__) - {"version"}
        if unknown:
            raise ValueError("Unknown template setting")
        captions = _bool(data.get("captions"), "Captions", True)
        hook = _bool(data.get("hook"), "Opening hook", True)
        end_card = _bool(data.get("end_card"), "End card", False)
        config = cls(
            framing=_enum(Framing, data.get("framing"), "framing") or Framing.AUTO,
            captions=captions,
            caption_preset=_enum(DynamicPreset, data.get("caption_preset"), "caption style")
            if captions
            else None,
            caption_position=_enum(
                CaptionPosition, data.get("caption_position"), "caption position"
            )
            if captions
            else None,
            hook=hook,
            hook_style=_enum(HookStyle, data.get("hook_style"), "hook style") if hook else None,
            hook_position=_enum(HookPosition, data.get("hook_position"), "hook position")
            if hook
            else None,
            hook_seconds=_seconds(
                data.get("hook_seconds"), (MIN_HOOK_SECONDS, MAX_HOOK_SECONDS), "The hook"
            )
            if hook
            else None,
            broll=_enum(BrollAmount, data.get("broll"), "B-roll amount") or BrollAmount.RECIPE,
            music_level=_enum(MusicLevel, data.get("music_level"), "music level"),
            ducking=_enum(DuckingStrength, data.get("ducking"), "ducking"),
            sound_effects=_bool(data.get("sound_effects"), "Sound effects", True),
            normalize_loudness=_bool(data.get("normalize_loudness"), "Loudness", True),
            logo=_bool(data.get("logo"), "Logo", True),
            end_card=end_card,
            end_card_seconds=(
                _seconds(data.get("end_card_seconds"), END_CARD_SECONDS, "The end card")
                or DEFAULT_END_CARD_SECONDS
            )
            if end_card
            else None,
        )
        if (
            config.caption_position is not None
            and config.hook_position is not None
            and config.caption_position.value == config.hook_position.value
        ):
            raise ValueError("The hook and the captions cannot share the same position")
        return config

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "TemplateConfig":
        if not isinstance(snapshot, dict) or snapshot.get("version") != TEMPLATE_CONFIG_VERSION:
            raise ValueError("Unsupported template version")
        return cls.create({k: v for k, v in snapshot.items() if k != "version"})

    @classmethod
    def from_recipe(cls, recipe: Recipe) -> "TemplateConfig":
        """A starting point that matches a recipe's own defaults."""
        return cls.create(
            {
                "caption_preset": recipe.caption_presets[0].value,
                "caption_position": recipe.caption_positions[0].value,
                "hook": recipe.hook_allowed,
                "hook_style": recipe.hook_styles[0].value if recipe.hook_allowed else None,
                "hook_seconds": recipe.hook_seconds if recipe.hook_allowed else None,
                "music_level": recipe.music_levels[0].value if recipe.music_levels else None,
                "ducking": recipe.ducking[0].value if recipe.ducking else None,
                "sound_effects": recipe.max_sfx > 0,
                "broll": BrollAmount.LIGHT.value if recipe.max_visuals <= 1 else "recipe",
            }
        )

    def snapshot(self) -> dict[str, Any]:
        values = {k: (v.value if isinstance(v, StrEnum) else v) for k, v in asdict(self).items()}
        return {"version": TEMPLATE_CONFIG_VERSION, **values}
