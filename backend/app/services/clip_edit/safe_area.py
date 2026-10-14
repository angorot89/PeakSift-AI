"""The General Social Safe Area: where caption and hook text stay readable in a 9:16 short.

Short-form apps draw their own interface over the video — navigation and tabs at the top,
the caption/description and buttons at the bottom, a column of actions on one side — and
those interfaces differ between apps and change over time. There is no single guaranteed
safe area, so PeakSift uses one conservative, versioned guide: keep text inside these
normalized margins of the 1080 × 1920 output frame. Side margins are symmetric because
captions are centred (and apps place their action column on either side).

Everything that positions text uses this one definition: the dynamic caption renderer, the
hook overlay, and — through ``GET /caption-styles`` — the browser preview and its optional
"Show safe area" guide. Changing a value means a new ``SAFE_AREA_VERSION``.
"""

from dataclasses import dataclass

from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH, CaptionPosition

SAFE_AREA_VERSION = "general_social_v1"


@dataclass(frozen=True)
class SafeArea:
    top: float
    bottom: float
    left: float
    right: float

    def px(self) -> dict[str, int]:
        return {
            "top": round(self.top * OUTPUT_HEIGHT),
            "bottom": round(self.bottom * OUTPUT_HEIGHT),
            "left": round(self.left * OUTPUT_WIDTH),
            "right": round(self.right * OUTPUT_WIDTH),
        }


GENERAL_SOCIAL = SafeArea(top=0.10, bottom=0.22, left=0.09, right=0.09)


@dataclass(frozen=True)
class Placement:
    """Where a text block is anchored: ASS numpad alignment and margins in output pixels."""

    alignment: int  # 8 = top centre, 5 = middle centre, 2 = bottom centre
    margin_v: int
    margin_h: int


def caption_placement(position: CaptionPosition, area: SafeArea = GENERAL_SOCIAL) -> Placement:
    """Top / Center / Bottom mapped into the safe area (not onto the frame edges)."""
    px = area.px()
    margin_h = max(px["left"], px["right"])
    if position == CaptionPosition.TOP:
        return Placement(8, px["top"], margin_h)
    if position == CaptionPosition.CENTER:
        return Placement(5, 0, margin_h)
    return Placement(2, px["bottom"], margin_h)
