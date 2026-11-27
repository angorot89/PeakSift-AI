"""Tighten: parts of the clip a Short leaves out (pauses, or segments the creator deleted).

An edit's ``cuts`` section lists removed ranges in the clip's own time (seconds from the start
of the generated clip). Everything else in the edit — the hook, visuals, sound effects, the
logo and the end card — is placed on the *Short's* timeline, which is what the editor shows;
only data that comes from the source (word timings, transcript phrases, the framing path) is
moved onto that timeline here, by ``to_output``.

Ranges are validated and normalized (rounded, sorted, merged), never repaired: a range outside
the clip or a cut that leaves too little is refused. The section appears in the snapshot only
when something is removed, so every earlier edit keeps its fingerprint.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

CUTS_VERSION = "cuts_v1"
DECIMALS = 3  # a millisecond: finer drag noise must not create a new render
MIN_CUT_SECONDS = 0.05  # shorter gaps are not worth a join
MIN_KEPT_SECONDS = 1.0  # a Short needs something left to show
MIN_PIECE_SECONDS = 0.04  # a kept sliver shorter than about a frame is folded into the cut
MAX_CUTS = 300
# A cut may end this far past the clip's probed end (container rounding), never further.
END_TOLERANCE_SECONDS = 0.05


def _seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError("Cut times must be numbers of seconds")
    return round(float(value), DECIMALS)


@dataclass(frozen=True)
class CutsConfig:
    """Removed ranges, sorted, non-overlapping, each at least ``MIN_CUT_SECONDS`` long."""

    removed: tuple[tuple[float, float], ...]

    @classmethod
    def create(cls, value: Any) -> "CutsConfig | None":
        """Validate (ValueError otherwise) and normalize; None when nothing is removed."""
        if value is None:
            return None
        if isinstance(value, CutsConfig):
            return value
        ranges = value.get("removed") if isinstance(value, dict) else value
        if ranges is None:
            return None
        if not isinstance(ranges, list | tuple):
            raise ValueError("Cuts must be a list of [start, end] ranges")
        if len(ranges) > MAX_CUTS:
            raise ValueError(f"A Short can leave out at most {MAX_CUTS} parts")
        spans: list[tuple[float, float]] = []
        for item in ranges:
            if not isinstance(item, list | tuple) or len(item) != 2:
                raise ValueError("Each cut is a [start, end] pair")
            start, end = _seconds(item[0]), _seconds(item[1])
            if start < 0 or end <= start:
                raise ValueError("A cut must end after it starts, inside the clip")
            spans.append((start, end))
        merged: list[tuple[float, float]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1] + MIN_PIECE_SECONDS:  # overlapping or a sliver
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        kept = tuple((s, e) for s, e in merged if e - s >= MIN_CUT_SECONDS)
        return cls(kept) if kept else None

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any] | None) -> "CutsConfig | None":
        if snapshot is None:
            return None
        if not isinstance(snapshot, dict) or snapshot.get("version") != CUTS_VERSION:
            raise ValueError("Unsupported cuts version")
        return cls.create(snapshot.get("removed"))

    def snapshot(self) -> dict[str, Any]:
        return {"version": CUTS_VERSION, "removed": [[s, e] for s, e in self.removed]}

    # --- against a clip ---------------------------------------------------------------

    def check(self, duration: float) -> None:
        """Refuse cuts that leave the clip or leave too little of it (ValueError)."""
        if self.removed[-1][1] > duration + END_TOLERANCE_SECONDS:
            raise ValueError("A cut ends after the end of the clip")
        if self.output_duration(duration) < MIN_KEPT_SECONDS:
            raise ValueError("Leave at least one second of the clip")

    def kept(self, duration: float) -> list[tuple[float, float]]:
        """The parts of ``[0, duration]`` that stay, in order (slivers folded away)."""
        pieces: list[tuple[float, float]] = []
        cursor = 0.0
        for start, end in self.removed:
            if start - cursor >= MIN_PIECE_SECONDS:
                pieces.append((cursor, min(start, duration)))
            cursor = max(cursor, end)
            if cursor >= duration:
                break
        if duration - cursor >= MIN_PIECE_SECONDS:
            pieces.append((cursor, duration))
        return [(s, e) for s, e in pieces if e > s]

    def output_duration(self, duration: float) -> float:
        return sum(e - s for s, e in self.kept(duration))

    def to_output(self, t: float) -> float:
        """Clip time → Short time. A time inside a removed range lands on its join."""
        shift = 0.0
        for start, end in self.removed:
            if t >= end:
                shift += end - start
            elif t > start:
                return start - shift
            else:
                break
        return t - shift

    def is_removed(self, t: float) -> bool:
        return any(start < t < end for start, end in self.removed)

    def span(self, start: float, end: float) -> tuple[float, float] | None:
        """A clip-time span on the Short's timeline; None when nothing of it remains."""
        out_start, out_end = self.to_output(start), self.to_output(end)
        return (out_start, out_end) if out_end - out_start > 1e-3 else None


def remap_words(cuts: CutsConfig, words: Iterable[Any], make: Any) -> list[Any]:
    """Words (``.start``/``.end`` in clip time) on the Short's timeline: a word that was cut
    away is dropped, one a cut runs through keeps what remains. ``make(word, start, end)``
    builds the moved word."""
    moved = []
    for word in words:
        span = cuts.span(word.start, word.end)
        if span is not None:
            moved.append(make(word, *span))
    return moved


def remap_crop_points(cuts: CutsConfig, points: Sequence[Any], duration: float) -> list[Any]:
    """The framing path on the Short's timeline.

    Keyframes inside removed parts are dropped, the rest move with the cuts, and each kept
    piece starts with the framing the source had at that moment (interpolated), so the crop
    jumps with the picture at a join instead of drifting across it.
    """
    if not points:
        return []
    cls = type(points[0])

    def at(t: float) -> Any:
        if t <= points[0].timestamp:
            return points[0]
        for before, after in zip(points, points[1:], strict=False):
            if before.timestamp <= t <= after.timestamp:
                span = after.timestamp - before.timestamp
                f = 0.0 if span <= 0 else (t - before.timestamp) / span
                return cls(
                    t,
                    before.center_x + (after.center_x - before.center_x) * f,
                    before.center_y + (after.center_y - before.center_y) * f,
                    before.crop_width,
                    before.crop_height,
                )
        return points[-1]

    moved: dict[float, Any] = {}
    for start, end in cuts.kept(duration):
        out_start = round(cuts.to_output(start), DECIMALS)
        moved.setdefault(out_start, at(start))
        for point in points:
            if start < point.timestamp < end:
                moved.setdefault(round(cuts.to_output(point.timestamp), DECIMALS), point)
        # Hold this piece's last framing until the join, so the next piece starts fresh.
        out_end = round(cuts.to_output(start) + (end - start) - 0.001, DECIMALS)
        if out_end > out_start:
            moved.setdefault(out_end, at(end))
    return [
        cls(timestamp, point.center_x, point.center_y, point.crop_width, point.crop_height)
        for timestamp, point in sorted(moved.items())
    ]
