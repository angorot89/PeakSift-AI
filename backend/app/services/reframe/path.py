"""Smart crop path planning: turn tracked subjects into a stable 9:16 crop path.

Geometry (no zoom in V0.7). For a display-oriented source ``W × H`` and the 9:16 target:

- wider than 9:16 (landscape, square): the crop uses the full height, width ``H·9/16``; it pans
  horizontally (normalized ``crop_width = (H·9/16)/W``, ``crop_height = 1``);
- taller than 9:16: full width, height ``W·16/9``; it pans vertically;
- exactly 9:16: the crop is the whole frame and never moves.

From subject to camera, at a fixed internal step of ``STEP`` seconds:

1. **Target.** With a followed face, the target keeps the face inside a *dead zone* around the
   current crop centre: the target is the current centre clamped to
   ``[face − dead_zone·crop, face + dead_zone·crop]``, so a face drifting inside the zone
   moves nothing (no micro-panning) and a face leaving it is followed by the minimum
   movement. The face box must also keep ``face_margin·crop`` from both crop edges. Two faces
   that fit together (with margins) are framed as a group (their union's centre). Without a
   subject the target is the centre (fallback).
2. **Look-ahead.** The path is computed offline, so the target is read ``smoothing_seconds``
   ahead — this cancels the lag the smoothing would otherwise add to a moving subject.
3. **Smoothing.** Exponential smoothing with time constant ``smoothing_seconds`` (never
   overshoots).
4. **Speed limit.** The centre moves at most ``max_pan_per_second`` (fractions of the panned
   axis per second) — a detector jump can never become a camera teleport.
5. **Bounds.** The centre is clamped so the crop never leaves the source.

**Shot changes.** When tracking flags a *hand-off* (the followed face vanished and a face that
appeared after it takes over — what a hard cut looks like) and the new position is more than
``CUT_MIN_JUMP`` of the crop away, the camera cuts too: two keyframes ``CUT_GAP`` apart, halfway
between the last sample of the old subject and the first of the new one (so the framing
switches within half a sample period of the real cut). Smoothing and the speed limit restart
from the new position, and the look-ahead never reads across a cut — the crop does not drift
toward a subject before it appears, nor pan slowly across unrelated shots afterwards. Faces
leaving and entering one continuous shot without a hand-off keep the smooth behaviour.

The dense path is reduced to sparse keyframes: a point is dropped when linear interpolation
between its neighbours reproduces it within ``SIMPLIFY_TOLERANCE`` (mode changes are always
kept). The renderer and the browser preview both interpolate linearly between keyframes.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.models.reframe import KeyframeMode, ReframeConfidence
from app.services.reframe.config import TARGET_RATIO, ReframeConfig
from app.services.reframe.tracking import SubjectSample, TrackPoint

STEP = 0.1  # internal simulation step, seconds
SETTLE_EPSILON = 1e-4
SIMPLIFY_TOLERANCE = 0.002  # in fractions of the panned axis (~4 px across a 1920 px frame)
MAX_KEYFRAMES = 5000
GROUP_MIN_RELATIVE_SIZE = 0.6  # a second face joins the frame only if it is this prominent
GROUP_HOLD_SECONDS = 1.0  # entering/leaving group framing needs this much stable evidence
CUT_MIN_JUMP = 0.25  # a hand-off cuts the camera only if it moves this much (crop fractions)
CUT_GAP = 0.001  # seconds between the two keyframes of a camera cut

# Confidence summary thresholds (documented; not a probability of "correct" framing).
HIGH_COVERAGE = 0.8
HIGH_CONFIDENCE = 0.6
FALLBACK_COVERAGE = 0.25


@dataclass(frozen=True)
class CropGeometry:
    """The fixed crop size (normalized) and the axis it pans along ('x', 'y' or None)."""

    crop_width: float
    crop_height: float
    axis: str | None

    @classmethod
    def for_source(cls, width: int, height: int, ratio: float = TARGET_RATIO) -> "CropGeometry":
        if width <= 0 or height <= 0:
            raise ValueError("source size must be positive")
        source_ratio = width / height
        if math.isclose(source_ratio, ratio, rel_tol=1e-3):
            return cls(1.0, 1.0, None)
        if source_ratio > ratio:  # wider than 9:16: full height, pan horizontally
            return cls(min(1.0, height * ratio / width), 1.0, "x")
        return cls(1.0, min(1.0, width / ratio / height), "y")  # taller: full width, pan vertically

    @property
    def size(self) -> float:
        """The crop's extent along the panned axis."""
        return (
            self.crop_width if self.axis == "x" else self.crop_height if self.axis == "y" else 1.0
        )

    def clamp(self, center: float) -> float:
        half = self.size / 2
        return min(1 - half, max(half, center))


@dataclass(frozen=True)
class PlannedKeyframe:
    timestamp: float
    center_x: float
    center_y: float
    crop_width: float
    crop_height: float
    confidence: float
    mode: KeyframeMode


@dataclass(frozen=True)
class CropPlan:
    keyframes: list[PlannedKeyframe]
    geometry: CropGeometry
    overall_confidence: float
    confidence_level: ReframeConfidence
    fallback_fraction: float
    subject_switches: int
    # Engineering diagnostics (not user-facing claims).
    max_pan_speed: float  # fractions of the panned axis per second (camera cuts excluded)
    subject_in_crop_fraction: float  # sampled moments whose followed face lies fully in the crop
    camera_cuts: int = 0  # hand-offs turned into cuts instead of pans


@dataclass(frozen=True)
class _Target:
    timestamp: float
    low: float  # face (or group) extent along the panned axis
    high: float
    center: float
    confidence: float
    mode: KeyframeMode


def _extent(point: TrackPoint, axis: str) -> tuple[float, float, float]:
    if axis == "x":
        return point.center_x - point.width / 2, point.center_x + point.width / 2, point.center_x
    return point.center_y - point.height / 2, point.center_y + point.height / 2, point.center_y


def _targets(
    samples: Sequence[SubjectSample], geometry: CropGeometry, config: ReframeConfig
) -> list[_Target]:
    """Per sample: what the crop should contain — one face, a two-face group, or nothing."""
    axis = geometry.axis or "x"
    usable = geometry.size * (1 - 2 * config.face_margin)
    targets: list[_Target] = []
    grouped = False
    group_since: float | None = None  # when the current group / solo condition started to flip
    for sample in samples:
        if sample.primary is None:
            targets.append(_Target(sample.timestamp, 0.5, 0.5, 0.5, 0.0, KeyframeMode.FALLBACK))
            grouped, group_since = False, None
            continue
        low, high, center = _extent(sample.primary, axis)
        confidence = sample.primary.confidence
        partner = None
        for other in sorted(sample.others, key=lambda p: (-p.width * p.height, p.track_id)):
            if (
                other.width * other.height
                >= GROUP_MIN_RELATIVE_SIZE * sample.primary.width * sample.primary.height
            ):
                partner = other
                break
        fits = False
        if partner is not None:
            p_low, p_high, _ = _extent(partner, axis)
            fits = max(high, p_high) - min(low, p_low) <= usable
        # Hysteresis: the group/solo decision flips only after GROUP_HOLD_SECONDS of evidence.
        if fits != grouped:
            if group_since is None:
                group_since = sample.timestamp
            if sample.timestamp - group_since >= GROUP_HOLD_SECONDS - 1e-9:
                grouped, group_since = fits, None
        else:
            group_since = None
        if grouped and partner is not None and fits:
            p_low, p_high, _ = _extent(partner, axis)
            low, high = min(low, p_low), max(high, p_high)
            center = (low + high) / 2
            confidence = min(confidence, partner.confidence)
            targets.append(
                _Target(sample.timestamp, low, high, center, confidence, KeyframeMode.GROUP)
            )
        else:
            targets.append(
                _Target(sample.timestamp, low, high, center, confidence, KeyframeMode.TRACKED)
            )
    return targets


def _target_at(targets: Sequence[_Target], t: float) -> _Target:
    """The target in force at time t (the latest sample at or before t)."""
    lo, hi = 0, len(targets) - 1
    if t <= targets[0].timestamp:
        return targets[0]
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if targets[mid].timestamp <= t + 1e-9:
            lo = mid
        else:
            hi = mid - 1
    return targets[lo]


def _desired(
    current: float, target: _Target, geometry: CropGeometry, config: ReframeConfig
) -> float:
    """Where the crop centre should go: stay inside the dead zone, respect face margins."""
    if target.mode == KeyframeMode.FALLBACK:
        return 0.5
    size = geometry.size
    zone = config.dead_zone * size
    desired = min(target.center + zone, max(target.center - zone, current))  # dead zone
    # Face margins: the whole face (or group) keeps face_margin·size from both crop edges.
    margin = config.face_margin * size
    low_bound = target.high + margin - size / 2  # centre must be at least this
    high_bound = target.low - margin + size / 2  # and at most this
    if low_bound <= high_bound:
        desired = min(high_bound, max(low_bound, desired))
    else:  # face larger than the usable area: centre on it
        desired = target.center
    return geometry.clamp(desired)


def _simplify(
    points: list[tuple[float, float, float, KeyframeMode]],
    tolerance: float,
    forced: set[int] | frozenset[int] = frozenset(),
) -> list[int]:
    """Indices to keep (iterative Douglas–Peucker on (t, centre); mode changes and ``forced``
    points — the two sides of a camera cut — are always kept)."""
    keep = {0, len(points) - 1} | set(forced)
    keep.update(i for i in range(1, len(points)) if points[i][3] != points[i - 1][3])
    anchors = sorted(keep)
    result = set(anchors)
    stack = list(zip(anchors, anchors[1:], strict=False))
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        (t0, c0, *_), (t1, c1, *_) = points[start], points[end]
        worst, worst_error = -1, tolerance
        for i in range(start + 1, end):
            t, c = points[i][0], points[i][1]
            expected = c0 + (c1 - c0) * ((t - t0) / (t1 - t0)) if t1 > t0 else c0
            error = abs(c - expected)
            if error > worst_error:
                worst, worst_error = i, error
        if worst >= 0:
            result.add(worst)
            stack.extend([(start, worst), (worst, end)])
    return sorted(result)


def plan_crop_path(
    samples: Sequence[SubjectSample],
    *,
    source_width: int,
    source_height: int,
    duration: float,
    config: ReframeConfig,
    switches: int = 0,
) -> CropPlan:
    """A smooth, bounded crop path for the whole clip (deterministic)."""
    if not (math.isfinite(duration) and duration > 0):
        raise ValueError("duration must be positive")
    geometry = CropGeometry.for_source(source_width, source_height)
    ordered = sorted(samples, key=lambda s: s.timestamp)
    targets = (
        _targets(ordered, geometry, config)
        if ordered
        else [_Target(0.0, 0.5, 0.5, 0.5, 0.0, KeyframeMode.FALLBACK)]
    )
    steps = max(1, math.ceil(duration / STEP - 1e-9))
    lead = config.smoothing_seconds
    alpha = 1 - math.exp(-STEP / config.smoothing_seconds) if config.smoothing_seconds > 0 else 1.0
    max_step = config.max_pan_per_second * STEP

    # Hand-offs: (cut moment, first sample of the new subject). The cut sits halfway between
    # the old subject's last sample and the new subject's first.
    cuts: list[tuple[float, float]] = []
    for before, after in zip(ordered, ordered[1:], strict=False):
        if after.cut and geometry.axis is not None:
            moment = round((before.timestamp + after.timestamp) / 2, 6)
            if CUT_GAP < moment < duration and (not cuts or moment - cuts[-1][0] > 2 * CUT_GAP):
                cuts.append((moment, after.timestamp))
    times = sorted(
        {min(duration, round(i * STEP, 6)) for i in range(steps + 1)}
        | {round(m - CUT_GAP, 6) for m, _ in cuts}
        | {m for m, _ in cuts}
    )
    times = [t for t in times if not any(1e-7 < abs(t - m) < CUT_GAP - 1e-7 for m, _ in cuts)]

    def lookahead(t: float) -> float:
        """t + lead, but never across the next cut (no drifting toward an unseen subject)."""
        ahead = min(duration, t + lead)
        for moment, _ in cuts:
            if t < moment <= ahead:
                return moment - CUT_GAP
        return ahead

    dense: list[tuple[float, float, float, KeyframeMode]] = []
    forced: set[int] = set()
    excluded: set[int] = set()  # dense intervals that are camera cuts (not pans)
    cut_at = dict(cuts)
    camera_cuts = 0
    current = geometry.clamp(_desired(0.5, _target_at(targets, lookahead(0.0)), geometry, config))
    if geometry.axis is None:
        current = 0.5
    for t in times:
        if t in cut_at and dense:
            first_new = cut_at[t]
            target = _target_at(targets, max(first_new, lookahead(t)))
            here = _target_at(targets, first_new)
            desired = _desired(current, target, geometry, config)
            if abs(desired - current) > CUT_MIN_JUMP * geometry.size:
                current = geometry.clamp(desired)  # cut with the shot: no smoothing, no limit
                forced.update({len(dense) - 1, len(dense)})
                excluded.add(len(dense))
                camera_cuts += 1
                dense.append((t, current, here.confidence, here.mode))
                continue
        target = _target_at(targets, lookahead(t))  # offline look-ahead cancels lag
        here = _target_at(targets, t)
        if geometry.axis is not None:
            desired = _desired(current, target, geometry, config)
            step = max_step * (t - dense[-1][0]) / STEP if dense else max_step
            fraction = 1 - math.exp(-(t - dense[-1][0]) / lead) if dense and lead > 0 else alpha
            moved = current + (desired - current) * fraction
            if abs(desired - moved) < SETTLE_EPSILON:
                moved = desired  # settle exactly instead of creeping asymptotically
            moved = current + max(-step, min(step, moved - current))  # speed limit
            current = geometry.clamp(moved)
        dense.append((t, current, here.confidence, here.mode))

    kept = _simplify(dense, SIMPLIFY_TOLERANCE, forced)
    if len(kept) > MAX_KEYFRAMES:  # pragma: no cover - bounded by duration / STEP in practice
        stride = math.ceil(len(kept) / MAX_KEYFRAMES)
        kept = sorted(set(kept[::stride]) | {kept[-1]})
    keyframes = []
    for i in kept:
        t, c, confidence, mode = dense[i]
        cx, cy = (
            (c, 0.5) if geometry.axis == "x" else (0.5, c) if geometry.axis == "y" else (0.5, 0.5)
        )
        keyframes.append(
            PlannedKeyframe(
                timestamp=round(t, 6),
                center_x=cx,
                center_y=cy,
                crop_width=geometry.crop_width,
                crop_height=geometry.crop_height,
                confidence=max(0.0, min(1.0, confidence)),
                mode=mode,
            )
        )

    # --- summary and diagnostics -------------------------------------------------------
    covered = [s for s in ordered if s.primary is not None]
    coverage = len(covered) / len(ordered) if ordered else 0.0
    mean_confidence = sum(s.primary.confidence for s in covered) / len(covered) if covered else 0.0
    overall = max(0.0, min(1.0, coverage * mean_confidence / (1 + 0.15 * switches)))
    if coverage < FALLBACK_COVERAGE:
        level = ReframeConfidence.FALLBACK
    elif coverage >= HIGH_COVERAGE and overall >= HIGH_CONFIDENCE:
        level = ReframeConfidence.HIGH
    else:
        level = ReframeConfidence.MIXED
    speeds = [
        abs(dense[i][1] - dense[i - 1][1]) / (dense[i][0] - dense[i - 1][0])
        for i in range(1, len(dense))
        if dense[i][0] > dense[i - 1][0] and i not in excluded
    ]
    inside = 0
    for sample in covered:
        c = crop_center_at(keyframes, sample.timestamp)
        center = c[0] if geometry.axis == "x" else c[1]
        low, high, _ = _extent(sample.primary, geometry.axis or "x")
        if geometry.axis is None or (
            center - geometry.size / 2 <= low + 1e-9 and high <= center + geometry.size / 2 + 1e-9
        ):
            inside += 1
    return CropPlan(
        keyframes=keyframes,
        geometry=geometry,
        overall_confidence=round(overall, 4),
        confidence_level=level,
        fallback_fraction=round(1 - coverage, 4) if ordered else 1.0,
        subject_switches=switches,
        max_pan_speed=round(max(speeds, default=0.0), 4),
        subject_in_crop_fraction=round(inside / len(covered), 4) if covered else 1.0,
        camera_cuts=camera_cuts,
    )


def crop_center_at(keyframes: Sequence[PlannedKeyframe], t: float) -> tuple[float, float]:
    """Linear interpolation between keyframes — the semantics the renderer and preview use."""
    if not keyframes:
        return 0.5, 0.5
    if t <= keyframes[0].timestamp:
        return keyframes[0].center_x, keyframes[0].center_y
    for a, b in zip(keyframes, keyframes[1:], strict=False):
        if a.timestamp <= t <= b.timestamp:
            f = (
                (t - a.timestamp) / (b.timestamp - a.timestamp)
                if b.timestamp > a.timestamp
                else 0.0
            )
            return a.center_x + (b.center_x - a.center_x) * f, a.center_y + (
                b.center_y - a.center_y
            ) * f
    return keyframes[-1].center_x, keyframes[-1].center_y
