"""The caption style specification served to the editor (one source of truth for the preview)."""

from typing import Literal

from pydantic import BaseModel


class SafeAreaRead(BaseModel):
    version: str
    # Normalized margins of the 1080 × 1920 output frame.
    top: float
    bottom: float
    left: float
    right: float


class PlacementRead(BaseModel):
    alignment: int  # ASS numpad: 8 top, 5 middle, 2 bottom (all horizontally centred)
    margin_v: int  # output pixels
    margin_h: int


class DynamicPresetRead(BaseModel):
    name: str
    label: str
    size: int  # libass font size on the 1080 × 1920 canvas (see font.em_per_size)
    bold: bool
    uppercase: bool
    text: str  # #RRGGBB
    active: str
    outline_colour: str
    outline: float
    shadow: float
    box: bool
    box_alpha: int
    fade_ms: int
    grow_from: int
    grow_ms: int


class HookStyleRead(BaseModel):
    name: str
    label: str
    size: int
    bold: bool
    text: str
    outline_colour: str
    outline: float
    shadow: float
    box: bool
    box_alpha: int
    max_line_width: int


class HookSpecRead(BaseModel):
    max_chars: int
    max_lines: int
    min_seconds: float
    max_seconds: float
    default_seconds: float
    fade_in_ms: int
    fade_out_ms: int
    styles: list[HookStyleRead]
    positions: dict[str, PlacementRead]


class FontRead(BaseModel):
    family: str
    # libass treats the font size as the line height: one em is this fraction of the size.
    em_per_size: float


class CaptionStylesRead(BaseModel):
    renderer: str
    # How emoji appear in burned-in text on this server: drawn with a monochrome emoji font,
    # or left out (libass cannot draw colour emoji). Never colour.
    emoji: Literal["monochrome", "omitted"]
    output_width: int
    output_height: int
    font: FontRead
    safe_area: SafeAreaRead
    positions: dict[str, PlacementRead]
    presets: list[DynamicPresetRead]
    hook: HookSpecRead
