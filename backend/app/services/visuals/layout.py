"""Where visual elements sit in the 1080 × 1920 short — one definition for renderer and preview.

- A **cutaway** covers the whole frame.
- A **picture-in-picture** or **overlay** fits inside a box whose width is a fraction of the
  frame (small / medium / large) and whose height is at most ``INSET_MAX_ASPECT`` × its width;
  the asset keeps its own proportions inside the box (never stretched). Picture-in-picture
  gets a thin white frame; overlays do not (they are often transparent badges or logos).
- Corners are placed inside the General Social Safe Area (``clip_edit/safe_area.py``), so an
  inset does not sit under app interfaces; captions and the hook are drawn *above* visuals,
  so text stays readable whatever the inset covers.

``layout_summary()`` is published to the editor (``GET /visual-layout``) so its preview places
boxes with the same numbers.
"""

from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH
from app.services.clip_edit.safe_area import GENERAL_SOCIAL
from app.services.visuals.config import VisualPosition, VisualSize

INSET_WIDTH_FRACTION = {VisualSize.SMALL: 0.34, VisualSize.MEDIUM: 0.44, VisualSize.LARGE: 0.56}
INSET_MAX_ASPECT = 1.25  # box height = width × 1.25 (portrait assets stay large enough)
PIP_BORDER = 6  # pixels of white frame around a picture-in-picture
BACKGROUND = "0x111113"  # behind transparent parts of cutaways and picture-in-picture

_MARGINS = GENERAL_SOCIAL.px()


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def inset_box(size: VisualSize) -> tuple[int, int]:
    """The (width, height) box an inset is fitted into, before any frame."""
    width = _even(OUTPUT_WIDTH * INSET_WIDTH_FRACTION[size])
    return width, _even(width * INSET_MAX_ASPECT)


def inset_position(position: VisualPosition) -> tuple[str, str]:
    """FFmpeg ``overlay`` x/y expressions (``w``/``h`` are the inset's real size)."""
    left, right = _MARGINS["left"], _MARGINS["right"]
    top, bottom = _MARGINS["top"], _MARGINS["bottom"]
    x = {
        VisualPosition.TOP_LEFT: f"{left}",
        VisualPosition.BOTTOM_LEFT: f"{left}",
        VisualPosition.TOP_RIGHT: f"W-w-{right}",
        VisualPosition.BOTTOM_RIGHT: f"W-w-{right}",
        VisualPosition.CENTER: "(W-w)/2",
    }[position]
    y = {
        VisualPosition.TOP_LEFT: f"{top}",
        VisualPosition.TOP_RIGHT: f"{top}",
        VisualPosition.BOTTOM_LEFT: f"H-h-{bottom}",
        VisualPosition.BOTTOM_RIGHT: f"H-h-{bottom}",
        VisualPosition.CENTER: "(H-h)/2",
    }[position]
    return x, y


def layout_summary() -> dict:
    """The numbers the editor's preview needs to place insets exactly like the renderer."""
    return {
        "output": {"width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT},
        "margins": dict(_MARGINS),
        "inset_width_fraction": {size.value: f for size, f in INSET_WIDTH_FRACTION.items()},
        "inset_max_aspect": INSET_MAX_ASPECT,
        "pip_border": PIP_BORDER,
        "background": "#" + BACKGROUND.removeprefix("0x"),
    }
