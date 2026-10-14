"""The editing options a user may choose, their normalized snapshot and its fingerprint.

Only allow-listed values exist here — never filter strings, fonts, paths, URLs or FFmpeg
arguments. A configuration is normalized before it is stored or compared, so equivalent
requests (for example captions off with different style choices) get the same fingerprint
and therefore the same edit.
"""

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.clip_edit.hook import HookConfig

CONFIG_VERSION = 1

# The canonical V0.6 output: 9:16 at 1080 × 1920.
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
RENDER_PROFILE_VERTICAL_V1 = "vertical_1080x1920_v1"


class AspectRatio(StrEnum):
    VERTICAL = "9:16"


class Layout(StrEnum):
    CENTER_CROP = "center_crop"  # fill the frame, crop the centre
    BLUR_BACKGROUND = "blur_background"  # whole frame over a blurred, filled copy
    FIT = "fit"  # whole frame on a plain dark background
    SMART_REFRAME = "smart_reframe"  # 9:16 crop following a completed face-tracking path
    MANUAL_CROP = "manual_crop"  # fixed 9:16 crop around a focal point the user chose


class CaptionStyle(StrEnum):
    CLEAN = "clean"
    BOLD = "bold"
    CREATOR = "creator"


class CaptionPosition(StrEnum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


DEFAULT_CAPTION_STYLE = CaptionStyle.BOLD
DEFAULT_CAPTION_POSITION = CaptionPosition.BOTTOM


FOCUS_DECIMALS = 3  # 0.1 % of the frame: finer slider noise must not create a new render


def _focus(value: float | None) -> float:
    """A focal coordinate in [0, 1], rounded so near-identical choices share one render."""
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Manual crop needs a focal point (x and y between 0 and 1)")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("The focal point must lie inside the frame (0 to 1)")
    return round(float(value), FOCUS_DECIMALS)


@dataclass(frozen=True)
class EditConfig:
    """A validated, normalized edit configuration."""

    aspect_ratio: AspectRatio
    layout: Layout
    captions_enabled: bool
    caption_style: CaptionStyle | None
    caption_position: CaptionPosition | None
    # Smart reframe only: the completed ReframeAnalysis whose crop path the render follows.
    reframe_analysis_id: str | None = None
    # Manual crop only: the focal point, as fractions of the display-oriented source frame.
    focus_x: float | None = None
    focus_y: float | None = None
    # The optional opening hook overlay (see hook.py); None = no hook.
    hook: "HookConfig | None" = None

    @classmethod
    def create(
        cls,
        *,
        aspect_ratio: str = AspectRatio.VERTICAL,
        layout: str,
        captions_enabled: bool,
        caption_style: str | None = None,
        caption_position: str | None = None,
        reframe_analysis_id: str | uuid.UUID | None = None,
        focus_x: float | None = None,
        focus_y: float | None = None,
        hook_enabled: bool = False,
        hook_text: str | None = None,
        hook_style: str | None = None,
        hook_position: str | None = None,
        hook_duration: float | None = None,
    ) -> "EditConfig":
        """Validate against the allow-lists (ValueError otherwise) and normalize."""
        from app.services.clip_edit.hook import HookConfig

        if not isinstance(hook_enabled, bool):
            raise ValueError("hook_enabled must be a boolean")
        hook = (
            HookConfig.create(
                text=hook_text, style=hook_style, position=hook_position, duration=hook_duration
            )
            if hook_enabled
            else None
        )
        ratio = AspectRatio(aspect_ratio)
        chosen_layout = Layout(layout)
        if not isinstance(captions_enabled, bool):
            raise ValueError("captions_enabled must be a boolean")
        analysis: str | None = None
        if chosen_layout == Layout.SMART_REFRAME:
            if reframe_analysis_id is None:
                raise ValueError("Smart reframe needs a completed framing analysis")
            analysis = str(uuid.UUID(str(reframe_analysis_id)))
        focus = (None, None)
        if chosen_layout == Layout.MANUAL_CROP:
            focus = (_focus(focus_x), _focus(focus_y))
        if not captions_enabled:
            # Style and position are meaningless without captions: drop them so equivalent
            # requests share one fingerprint (and one render).
            return cls(ratio, chosen_layout, False, None, None, analysis, *focus, hook)
        style = CaptionStyle(caption_style) if caption_style else DEFAULT_CAPTION_STYLE
        position = (
            CaptionPosition(caption_position) if caption_position else DEFAULT_CAPTION_POSITION
        )
        if hook is not None and hook.position.value == position.value:
            raise ValueError("The hook and the captions cannot share the same position")
        return cls(ratio, chosen_layout, True, style, position, analysis, *focus, hook)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "EditConfig":
        if not isinstance(snapshot, dict) or snapshot.get("version") != CONFIG_VERSION:
            raise ValueError("Unsupported edit configuration version")
        captions = snapshot.get("captions") or {}
        hook = snapshot.get("hook")
        return cls.create(
            aspect_ratio=snapshot.get("aspect_ratio", AspectRatio.VERTICAL),
            layout=snapshot.get("layout"),
            captions_enabled=bool(captions.get("enabled", False)),
            caption_style=captions.get("style"),
            caption_position=captions.get("position"),
            reframe_analysis_id=(snapshot.get("reframe") or {}).get("analysis_id"),
            focus_x=(snapshot.get("focus") or {}).get("x"),
            focus_y=(snapshot.get("focus") or {}).get("y"),
            hook_enabled=hook is not None,
            hook_text=(hook or {}).get("text"),
            hook_style=(hook or {}).get("style"),
            hook_position=(hook or {}).get("position"),
            hook_duration=(hook or {}).get("duration"),
        )

    def snapshot(self) -> dict[str, Any]:
        """The exact parameters a render uses, stored on the edit (never future defaults).

        The ``reframe``, ``focus`` and ``hook`` keys exist only when used, so every earlier
        configuration keeps exactly its previous snapshot and fingerprint (repeat requests
        still deduplicate).
        """
        snapshot: dict[str, Any] = {
            "version": CONFIG_VERSION,
            "aspect_ratio": self.aspect_ratio.value,
            "layout": self.layout.value,
            "output": {"width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT},
            "captions": {
                "enabled": self.captions_enabled,
                "style": self.caption_style.value if self.caption_style else None,
                "position": self.caption_position.value if self.caption_position else None,
            },
        }
        if self.layout == Layout.SMART_REFRAME:
            snapshot["reframe"] = {"analysis_id": self.reframe_analysis_id}
        if self.layout == Layout.MANUAL_CROP:
            snapshot["focus"] = {"x": self.focus_x, "y": self.focus_y}
        if self.hook is not None:
            snapshot["hook"] = self.hook.snapshot()
        return snapshot

    def fingerprint(self) -> str:
        """sha256 of the canonical JSON snapshot: equal configurations, equal fingerprints."""
        canonical = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
