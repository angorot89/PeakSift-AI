"""The brand part of an edit: the exact identity values a Short is rendered with.

A brand is copied into the edit's snapshot — never read from ``BrandProfile`` at render time —
so a Short keeps its look when the brand or template changes or is deleted. The section exists
only when it changes something (old edits keep their snapshot and fingerprint) and holds:

- **logo**: one of the creator's image visual assets, a corner and a size. The renderer draws it
  over the picture and visuals and under the captions and hook, fitted inside a square box
  (never stretched; transparency kept).
- **caption emphasis**: the colour of the spoken word in dynamic captions — kept only when it
  is readable as text (WCAG AA on the presets' dark surround, ``branding/colors.py``); an
  unreadable colour is dropped here rather than rendered.
- **hook accent**: the label colour of the *Boxed* hook, with dark or white text — whichever
  reads better; kept only if that text reaches AA on it.
- **end card**: ``seconds`` appended after the clip (the Short gets longer by exactly that, and
  the editor says so): the brand colour as background, the logo if there is one, the brand name
  and the creator's own line. Silent: the clip's sound is never repeated or stretched.

**Logo placement policy** (``logo_plan``), the same in the preview: the logo goes in its corner
inside the General Social Safe Area, except —

1. captions at the bottom and a bottom corner → the logo moves to the top corner on the same side
   (captions at the top → bottom corner); captions in the centre or off → no move;
2. the hook at the top and the logo at the top → the logo appears once the hook has ended;
3. a picture-in-picture or overlay inset in the same corner → the logo is hidden while it shows.

Only allow-listed enums, validated colours and module-formatted numbers reach the renderer.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.services.branding.colors import (
    emphasis_readable,
    normalize_color,
    readable_on,
    text_on,
)
from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH
from app.services.clip_edit.safe_area import GENERAL_SOCIAL

BRAND_VERSION = "brand_v1"
NAME_MAX = 60
END_CARD_TEXT_MAX = 40
END_CARD_SECONDS = (1.0, 3.0)
LOGO_WIDTH_FRACTION = {"small": 0.16, "medium": 0.22, "large": 0.28}  # a square box
CARD_LOGO_FRACTION = 0.34
CARD_LOGO_CENTER_Y = 0.36  # of the frame height
CARD_NAME_Y = 0.56
CARD_TEXT_Y = 0.63


class LogoCorner(StrEnum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"

    @property
    def top(self) -> bool:
        return self.value.startswith("top")

    def flipped(self) -> "LogoCorner":
        vertical, side = self.value.split("_")
        return LogoCorner(f"{'bottom' if vertical == 'top' else 'top'}_{side}")


class LogoSize(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


def _text(value: object, maximum: int, name: str, *, required: bool) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        if required:
            raise ValueError(f"The {name} is missing")
        return None
    if len(text) > maximum:
        raise ValueError(f"The {name} can be at most {maximum} characters")
    return text


@dataclass(frozen=True)
class BrandLogo:
    asset_id: str
    corner: LogoCorner
    size: LogoSize


@dataclass(frozen=True)
class EndCard:
    seconds: float
    background: str
    text: str | None
    show_logo: bool


@dataclass(frozen=True)
class BrandConfig:
    name: str
    logo: BrandLogo | None = None
    caption_emphasis: str | None = None
    hook_accent: str | None = None
    end_card: EndCard | None = None

    @property
    def empty(self) -> bool:
        return not (self.logo or self.caption_emphasis or self.hook_accent or self.end_card)

    @classmethod
    def create(cls, data: dict[str, Any] | None) -> "BrandConfig | None":
        """Validate and normalize; ``None`` when nothing is branded. Unreadable colours are
        dropped (never rendered as text)."""
        import uuid

        if not data:
            return None
        if not isinstance(data, dict):
            raise ValueError("The brand settings are not valid")
        name = _text(data.get("name"), NAME_MAX, "brand name", required=True)
        logo = None
        if data.get("logo"):
            raw = data["logo"]
            try:
                asset = str(uuid.UUID(str(raw.get("asset_id"))))
            except (TypeError, ValueError, AttributeError):
                raise ValueError("The logo must be one of your images") from None
            logo = BrandLogo(asset, LogoCorner(raw.get("corner")), LogoSize(raw.get("size")))
        emphasis = data.get("caption_emphasis")
        emphasis = normalize_color(emphasis) if emphasis else None
        if emphasis and not emphasis_readable(emphasis):
            emphasis = None
        accent = data.get("hook_accent")
        accent = normalize_color(accent) if accent else None
        if accent and not readable_on(text_on(accent), accent):
            accent = None
        card = None
        if data.get("end_card"):
            raw = data["end_card"]
            seconds = raw.get("seconds")
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, int | float)
                or not END_CARD_SECONDS[0] <= seconds <= END_CARD_SECONDS[1]
            ):
                raise ValueError("The end card lasts 1 to 3 seconds")
            card = EndCard(
                round(float(seconds), 1),
                normalize_color(raw.get("background")),
                _text(raw.get("text"), END_CARD_TEXT_MAX, "end-card line", required=False),
                bool(raw.get("show_logo")) and logo is not None,
            )
        config = cls(name, logo, emphasis, accent, card)
        return None if config.empty else config

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": BRAND_VERSION, "name": self.name}
        if self.logo:
            out["logo"] = {
                "asset_id": self.logo.asset_id,
                "corner": self.logo.corner.value,
                "size": self.logo.size.value,
            }
        if self.caption_emphasis:
            out["caption_emphasis"] = self.caption_emphasis
        if self.hook_accent:
            out["hook_accent"] = self.hook_accent
        if self.end_card:
            out["end_card"] = {
                "seconds": self.end_card.seconds,
                "background": self.end_card.background,
                "text": self.end_card.text,
                "show_logo": self.end_card.show_logo,
            }
        return out

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any] | None) -> "BrandConfig | None":
        if snapshot is None:
            return None
        if not isinstance(snapshot, dict) or snapshot.get("version") != BRAND_VERSION:
            raise ValueError("Unsupported brand settings version")
        return cls.create(snapshot)

    def without(self, *, emphasis: bool = False, accent: bool = False) -> "BrandConfig | None":
        """The same brand without settings that cannot apply (e.g. no dynamic captions)."""
        config = BrandConfig(
            self.name,
            self.logo,
            None if emphasis else self.caption_emphasis,
            None if accent else self.hook_accent,
            self.end_card,
        )
        return None if config.empty else config

    @property
    def extra_seconds(self) -> float:
        return self.end_card.seconds if self.end_card else 0.0


# --- layout (renderer and preview share these numbers) --------------------------------------------


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def logo_box(size: LogoSize) -> int:
    """The side of the square box a corner logo is fitted into (pixels)."""
    return _even(OUTPUT_WIDTH * LOGO_WIDTH_FRACTION[size])


def card_logo_box() -> int:
    return _even(OUTPUT_WIDTH * CARD_LOGO_FRACTION)


@dataclass(frozen=True)
class LogoPlan:
    corner: LogoCorner
    box: int
    visible_from: float  # seconds; the hook may keep the top clear first
    hidden: tuple[tuple[float, float], ...]  # insets in the same corner
    moved: bool  # the corner changed to stay clear of the captions


def logo_plan(
    logo: BrandLogo,
    *,
    captions_position: str | None,
    hook_position: str | None,
    hook_seconds: float,
    insets: list[tuple[str, float, float]],
) -> LogoPlan:
    """Where and when the corner logo shows (see the module's placement policy).
    ``insets``: (corner, start, end) of every picture-in-picture / overlay."""
    corner, moved = logo.corner, False
    if captions_position == "bottom" and not corner.top:
        corner, moved = corner.flipped(), True
    elif captions_position == "top" and corner.top:
        corner, moved = corner.flipped(), True
    visible_from = hook_seconds if (hook_position == "top" and corner.top) else 0.0
    hidden = tuple(sorted((start, end) for spot, start, end in insets if spot == corner.value))
    return LogoPlan(corner, logo_box(logo.size), round(visible_from, 3), hidden, moved)


def corner_xy(corner: LogoCorner) -> tuple[str, str]:
    """FFmpeg ``overlay`` x/y inside the safe area (``w``/``h``: the logo's real size)."""
    m = GENERAL_SOCIAL.px()
    x = f"{m['left']}" if corner.value.endswith("left") else f"W-w-{m['right']}"
    y = f"{m['top']}" if corner.top else f"H-h-{m['bottom']}"
    return x, y


def enable_expression(plan: LogoPlan) -> str:
    """When the corner logo is drawn, as a module-formatted FFmpeg expression."""
    parts = []
    if plan.visible_from > 0:
        parts.append(f"gte(t,{plan.visible_from:.3f})")
    if plan.hidden:
        spans = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in plan.hidden)
        parts.append(f"not({spans})")
    return "*".join(parts) or "1"


def layout_summary() -> dict[str, Any]:
    """Published for the Brand Studio and editor previews."""
    return {
        "logo_width_fraction": dict(LOGO_WIDTH_FRACTION),
        "card": {
            "logo_fraction": CARD_LOGO_FRACTION,
            "logo_center_y": CARD_LOGO_CENTER_Y,
            "name_y": CARD_NAME_Y,
            "text_y": CARD_TEXT_Y,
        },
        "end_card_seconds": list(END_CARD_SECONDS),
        "frame": {"width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT},
    }


def accent_text(accent: str) -> str:
    """The text colour on the hook's accent label."""
    return text_on(accent)
