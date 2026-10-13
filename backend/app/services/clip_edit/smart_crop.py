"""The FFmpeg side of smart reframing: a time-varying crop that follows a crop path.

The path is a list of validated numeric keyframes (from ``reframe_keyframes``). FFmpeg's
``crop`` filter evaluates its ``x``/``y`` expressions on every frame with ``t`` = the frame's
time, so the path is compiled into an expression that interpolates linearly between keyframes
— the same semantics as ``crop_center_at`` and the browser preview.

Why a balanced ``if(lt(t,T), left, right)`` tree: a flat sum of per-segment terms works for a
few dozen segments but FFmpeg's expression evaluator refuses deeper expressions (verified:
50 segments render, 100 fail with "Failed to configure input pad"). A balanced tree is only
log2(n) deep; 1000 segments (a 51 kB expression) were verified to render on FFmpeg 9.0.2 at
full speed. Paths are simplified long before that (MAX_SEGMENTS caps them anyway).

Nothing user-supplied reaches the filtergraph: every value is a finite float formatted as a
fixed-point number by this module, after validation.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MAX_SEGMENTS = 1000


@dataclass(frozen=True)
class CropPoint:
    timestamp: float
    center_x: float
    center_y: float
    crop_width: float
    crop_height: float


def crop_points_from(keyframes: Sequence[Any]) -> list[CropPoint]:
    """Validate persisted keyframes and return them as crop points. Raises ValueError.

    Every value must be finite, timestamps strictly increasing and non-negative, the crop the
    same size throughout (V0.7 pans, it does not zoom) and inside the source frame.
    """
    if not keyframes:
        raise ValueError("The crop path is empty")
    points: list[CropPoint] = []
    for k in keyframes:
        values = (k.timestamp, k.center_x, k.center_y, k.crop_width, k.crop_height)
        if not all(
            isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
            for v in values
        ):
            raise ValueError("The crop path contains invalid numbers")
        point = CropPoint(*(float(v) for v in values))
        if point.timestamp < 0 or (points and point.timestamp <= points[-1].timestamp):
            raise ValueError("The crop path is not ordered")
        if not (0 < point.crop_width <= 1 and 0 < point.crop_height <= 1):
            raise ValueError("The crop path has an invalid crop size")
        if points and (
            abs(point.crop_width - points[0].crop_width) > 1e-6
            or abs(point.crop_height - points[0].crop_height) > 1e-6
        ):
            raise ValueError("The crop size must not change along the path")
        half_w, half_h = point.crop_width / 2, point.crop_height / 2
        if (
            point.center_x - half_w < -1e-6
            or point.center_x + half_w > 1 + 1e-6
            or point.center_y - half_h < -1e-6
            or point.center_y + half_h > 1 + 1e-6
        ):
            raise ValueError("The crop path leaves the source frame")
        points.append(point)
    if len(points) > MAX_SEGMENTS + 1:  # thin uniformly, keeping both ends
        stride = math.ceil((len(points) - 1) / MAX_SEGMENTS)
        points = points[:-1:stride] + [points[-1]]
    return points


def _num(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}"
    return "0" if text in (f"-{0:.{decimals}f}",) else text


def _tree(times: list[float], values: list[float], lo: int, hi: int) -> str:
    if hi - lo == 1:
        t0, t1, v0, v1 = times[lo], times[hi], values[lo], values[hi]
        slope = (v1 - v0) / (t1 - t0)
        if abs(slope) < 1e-9:
            return _num(v0, 3)
        return f"{_num(v0, 3)}+{_num(slope, 6)}*(t-{_num(t0, 6)})"
    mid = (lo + hi) // 2
    left, right = _tree(times, values, lo, mid), _tree(times, values, mid, hi)
    return f"if(lt(t,{_num(times[mid], 6)}),{left},{right})"


def position_expression(times: list[float], values: list[float], limit: float) -> str:
    """Piecewise-linear expression of the crop offset (pixels), held before/after the path."""
    if all(abs(v - values[0]) < 1e-6 for v in values):
        return _num(min(limit, max(0.0, values[0])), 3)
    if len(times) == 1:
        return _num(values[0], 3)
    body = _tree(times, values, 0, len(times) - 1)
    held = (
        f"if(lt(t,{_num(times[0], 6)}),{_num(values[0], 3)},"
        f"if(gte(t,{_num(times[-1], 6)}),{_num(values[-1], 3)},{body}))"
    )
    return f"clip({held},0,{_num(limit, 3)})"


def crop_size_pixels(point: CropPoint, source_width: int, source_height: int) -> tuple[int, int]:
    """Crop size in source pixels: even (yuv420p), at least 2, never larger than the source."""
    width = min(source_width, max(2, int(round(point.crop_width * source_width))))
    height = min(source_height, max(2, int(round(point.crop_height * source_height))))
    return width - width % 2, height - height % 2


def smart_crop_filter(
    points: Sequence[CropPoint],
    source_width: int,
    source_height: int,
    out_width: int,
    out_height: int,
) -> str:
    """Filtergraph from ``[0:v]`` to ``[framed]``: follow the path, then scale to the output."""
    if source_width <= 0 or source_height <= 0:
        raise ValueError("The source size is invalid")
    crop_w, crop_h = crop_size_pixels(points[0], source_width, source_height)
    times = [p.timestamp for p in points]
    xs = [p.center_x * source_width - crop_w / 2 for p in points]
    ys = [p.center_y * source_height - crop_h / 2 for p in points]
    x = position_expression(times, xs, source_width - crop_w)
    y = position_expression(times, ys, source_height - crop_h)
    return (
        f"[0:v]crop=w={crop_w}:h={crop_h}:x='{x}':y='{y}':exact=0,"
        f"scale={out_width}:{out_height}:flags=lanczos,setsar=1[framed]"
    )
