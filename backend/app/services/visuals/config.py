"""The visual part of an edit: B-roll cutaways, picture-in-picture insets and image overlays.

Each element places one of the project's visual assets (by id) over an interval of the short
(clip-local seconds) in one of three modes:

- ``cutaway``: the asset replaces the picture for the interval (the original audio keeps
  playing; captions and the hook stay on top), filling the frame or fitted over a blurred
  copy of itself — never stretched;
- ``pip``: the asset in a bounded box in a corner, over the main video;
- ``overlay``: an image (transparency kept) in a bounded box, optionally semi-transparent.

Only validated numbers and allow-listed enums exist here — never filter strings, paths or
URLs. Values are rounded (times to 10 ms, opacity to 1 %) so slider noise does not create
new renders, options that do not apply to a mode are dropped, and elements are sorted, so
equivalent requests share one fingerprint. At any instant at most one cutaway and at most one
inset (pip or overlay) is shown: the frame never has two competing full-screen pictures.
A section without elements normalizes to "no visuals section", so edits without visuals keep
exactly their earlier snapshot and fingerprint.

What the configuration cannot know — whether an asset exists, belongs to the project, is an
image or a video, how long it is, and how long the clip is — is checked by the API and again
before every render.
"""

import math
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

VISUALS_VERSION = "visuals_v1"
MAX_ELEMENTS = 12
MIN_ELEMENT_SECONDS = 0.5
TIME_DECIMALS = 2
OPACITY_RANGE = (0.2, 1.0)
OPACITY_DECIMALS = 2


class VisualMode(StrEnum):
    CUTAWAY = "cutaway"
    PIP = "pip"
    OVERLAY = "overlay"


class VisualFit(StrEnum):
    FILL = "fill"  # cover the frame, cropping the edges
    FIT = "fit"  # the whole asset, over a blurred, filled copy of itself


class VisualPosition(StrEnum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    CENTER = "center"  # overlays only


class VisualSize(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


DEFAULT_FIT = VisualFit.FILL
DEFAULT_POSITION = VisualPosition.TOP_RIGHT
DEFAULT_SIZE = VisualSize.MEDIUM
INSET_MODES = (VisualMode.PIP, VisualMode.OVERLAY)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _seconds(value: object, name: str) -> float:
    number = _number(value, name)
    if number < 0:
        raise ValueError(f"{name} must not be negative")
    return round(number, TIME_DECIMALS) + 0.0


def _asset_id(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        raise ValueError("Each visual needs a visual asset id") from None


def _enum(kind: type[StrEnum], value: object, name: str) -> StrEnum:
    try:
        return kind(value)
    except ValueError:
        raise ValueError(f"Unsupported {name}") from None


@dataclass(frozen=True, order=True)
class VisualElement:
    start: float  # first, so elements sort by time
    end: float
    mode: VisualMode
    asset_id: str
    fit: VisualFit | None = None  # cutaway only
    position: VisualPosition | None = None  # pip / overlay
    size: VisualSize | None = None  # pip / overlay
    opacity: float | None = None  # overlay only (1.0 = opaque)
    asset_offset_seconds: float = 0.0  # videos: where playback starts inside the asset
    loop: bool = False  # videos: repeat when the asset is shorter than the element

    @property
    def duration(self) -> float:
        return round(self.end - self.start, TIME_DECIMALS)

    @property
    def is_inset(self) -> bool:
        return self.mode in INSET_MODES

    @classmethod
    def create(cls, data: dict[str, Any]) -> "VisualElement":
        if not isinstance(data, dict):
            raise ValueError("Each visual must be an object")
        mode = _enum(VisualMode, data.get("mode"), "visual mode")
        start = _seconds(data.get("start_seconds"), "Visual start")
        end = _seconds(data.get("end_seconds"), "Visual end")
        if end - start < MIN_ELEMENT_SECONDS:
            raise ValueError(f"A visual must last at least {MIN_ELEMENT_SECONDS:g} seconds")
        offset = _seconds(data.get("asset_offset_seconds", 0.0), "Video start")
        loop = data.get("loop", False)
        if not isinstance(loop, bool):
            raise ValueError("loop must be true or false")
        fit = position = size = opacity = None
        if mode == VisualMode.CUTAWAY:
            fit = _enum(VisualFit, data.get("fit") or DEFAULT_FIT, "fit")
        else:
            position = _enum(VisualPosition, data.get("position") or DEFAULT_POSITION, "position")
            if position == VisualPosition.CENTER and mode == VisualMode.PIP:
                raise ValueError("Picture-in-picture goes in a corner")
            size = _enum(VisualSize, data.get("size") or DEFAULT_SIZE, "size")
        if mode == VisualMode.OVERLAY:
            raw = data.get("opacity", 1.0)
            value = _number(1.0 if raw is None else raw, "Opacity")
            low, high = OPACITY_RANGE
            if not low <= value <= high:
                raise ValueError(f"Opacity must be between {low:g} and {high:g}")
            opacity = round(value, OPACITY_DECIMALS) + 0.0
        return cls(
            start=start,
            end=end,
            mode=mode,  # type: ignore[arg-type]
            asset_id=_asset_id(data.get("asset_id")),
            fit=fit,  # type: ignore[arg-type]
            position=position,  # type: ignore[arg-type]
            size=size,  # type: ignore[arg-type]
            opacity=opacity,
            asset_offset_seconds=offset,
            loop=loop,
        )

    def snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "asset_id": self.asset_id,
            "mode": self.mode.value,
            "start_seconds": self.start,
            "end_seconds": self.end,
            "asset_offset_seconds": self.asset_offset_seconds,
            "loop": self.loop,
        }
        if self.fit is not None:
            snapshot["fit"] = self.fit.value
        if self.position is not None:
            snapshot["position"] = self.position.value
            snapshot["size"] = self.size.value if self.size else None
        if self.opacity is not None:
            snapshot["opacity"] = self.opacity
        return snapshot


def _overlap(a: VisualElement, b: VisualElement) -> bool:
    return a.start < b.end and b.start < a.end


@dataclass(frozen=True)
class VisualsConfig:
    elements: tuple[VisualElement, ...]

    @classmethod
    def create(cls, data: dict[str, Any] | None) -> "VisualsConfig | None":
        """Validate and normalize; ``None`` when there is nothing to show."""
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValueError("visuals must be an object")
        items = data.get("elements") or []
        if not isinstance(items, list):
            raise ValueError("visuals.elements must be a list")
        if len(items) > MAX_ELEMENTS:
            raise ValueError(f"An edit can have at most {MAX_ELEMENTS} visuals")
        elements = tuple(sorted(VisualElement.create(item) for item in items))
        cutaways = [e for e in elements if e.mode == VisualMode.CUTAWAY]
        insets = [e for e in elements if e.is_inset]
        for group, label in (
            (cutaways, "cutaways"),
            (insets, "picture-in-picture or overlay visuals"),
        ):
            for first, second in zip(group, group[1:], strict=False):
                if _overlap(first, second):
                    raise ValueError(f"Two {label} cannot overlap; adjust their timing")
        return cls(elements) if elements else None

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any] | None) -> "VisualsConfig | None":
        if snapshot is None:
            return None
        if not isinstance(snapshot, dict) or snapshot.get("version") != VISUALS_VERSION:
            raise ValueError("Unsupported visuals configuration version")
        return cls.create({"elements": snapshot.get("elements")})

    @property
    def asset_ids(self) -> list[str]:
        return list(dict.fromkeys(e.asset_id for e in self.elements))

    @property
    def end(self) -> float:
        return max(e.end for e in self.elements)

    def snapshot(self) -> dict[str, Any]:
        return {"version": VISUALS_VERSION, "elements": [e.snapshot() for e in self.elements]}
