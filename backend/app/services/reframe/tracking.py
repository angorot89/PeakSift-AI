"""Temporal subject tracking: link per-frame face detections into tracks, then choose — with
hysteresis — which track the crop should follow at each sampled moment.

This is deliberately small and deterministic (creator footage has a handful of faces; no
tracking framework or SciPy is needed). It is *not* speaker detection: PeakSift has no
audio/visual speaker model, so "the subject" means the most prominent, persistent face.

**Association** (frame by frame, in time order). Each live track predicts its box at the new
timestamp from its last two observations (constant velocity, capped). A track and a detection
may match when the boxes overlap (IoU ≥ 0.1) or when the centre moved less than
``MAX_MATCH_DISTANCE`` face widths (scaled up for longer gaps) with a similar size (area ratio
≥ ``MIN_SIZE_RATIO``). Candidate pairs are taken greedily by cost
``distance − IoU`` (ties by track id, then detection order), one-to-one. Unmatched detections
start new tracks; tracks not seen for longer than ``max_gap_seconds`` stop matching.

**Positions between observations.** Inside a gap (≤ ``max_gap_seconds``) a track's position is
interpolated between its neighbouring observations, or held at the last one with confidence
decaying linearly to zero at the end of the gap — so one missed detection never teleports
the crop. After the gap the track is gone at that time.

**Choosing the subject** (offline: the whole clip is known). Tracks with fewer than
``MIN_OBSERVATIONS`` observations never steer (single-frame false positives). Visible tracks
are scored ``0.45·size + 0.30·persistence + 0.15·confidence + 0.10·centrality`` (size relative
to the largest visible face, persistence = observed duration up to 3 s, centrality = closeness
to the horizontal centre). The current subject stays until it disappears, or until another
track has outscored it by ``SWITCH_MARGIN`` (25 %) continuously for ``SWITCH_HOLD_SECONDS``.

**Hand-offs (shot changes).** When the followed face has ended (it is only being *held* past
its last observation) and a face that first appeared *after* that last observation is
visible, the new face takes over at once instead of waiting for the held box to expire: one
face vanishing as another appears elsewhere is what a hard cut looks like. Such a change of
subject is flagged ``cut`` so the crop path can cut with it instead of panning across the
frame. Faces that were visible together never produce a hand-off; they use the hysteresis
above.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.reframe.detection import SubjectDetection

MAX_MATCH_DISTANCE = 1.5  # in face widths, for one sample period
MIN_SIZE_RATIO = 0.4
MIN_IOU = 0.1
MAX_SPEED = 2.0  # predicted motion cap, frame widths per second
MIN_OBSERVATIONS = 2
SWITCH_MARGIN = 0.25
SWITCH_HOLD_SECONDS = 1.0
PERSISTENCE_SECONDS = 3.0
WEIGHTS = {"size": 0.45, "persistence": 0.30, "confidence": 0.15, "centrality": 0.10}


@dataclass(frozen=True)
class TrackPoint:
    """A track's (possibly interpolated) face box at one moment, in frame fractions."""

    track_id: int
    timestamp: float
    center_x: float
    center_y: float
    width: float
    height: float
    confidence: float
    observed: bool  # an actual detection at this timestamp (vs interpolated / held)

    @property
    def left(self) -> float:
        return self.center_x - self.width / 2

    @property
    def right(self) -> float:
        return self.center_x + self.width / 2


@dataclass
class Track:
    track_id: int
    observations: list[SubjectDetection] = field(default_factory=list)

    @property
    def first_seen(self) -> float:
        return self.observations[0].timestamp

    @property
    def last_seen(self) -> float:
        return self.observations[-1].timestamp

    @property
    def average_confidence(self) -> float:
        return sum(d.confidence for d in self.observations) / len(self.observations)

    @property
    def average_area(self) -> float:
        return sum(d.box.area for d in self.observations) / len(self.observations)

    def observed_duration(self, sample_period: float) -> float:
        return len(self.observations) * sample_period

    def predict(self, timestamp: float) -> tuple[float, float, float, float]:
        """(cx, cy, w, h) expected at ``timestamp`` from the last two observations."""
        last = self.observations[-1].box
        cx, cy = last.center_x, last.center_y
        if len(self.observations) >= 2:
            prev = self.observations[-2]
            dt = self.last_seen - prev.timestamp
            if dt > 0:
                vx = (last.center_x - prev.box.center_x) / dt
                vy = (last.center_y - prev.box.center_y) / dt
                speed = math.hypot(vx, vy)
                if speed > MAX_SPEED:
                    vx, vy = vx * MAX_SPEED / speed, vy * MAX_SPEED / speed
                ahead = timestamp - self.last_seen
                cx, cy = cx + vx * ahead, cy + vy * ahead
        return cx, cy, last.width, last.height

    def point_at(self, timestamp: float, max_gap: float) -> TrackPoint | None:
        """Observed, interpolated (inside a short gap) or held-and-decaying position, or None."""
        obs = self.observations
        if timestamp < obs[0].timestamp - 1e-9 or timestamp > obs[-1].timestamp + max_gap + 1e-9:
            return None
        # Binary search for the last observation at or before ``timestamp``.
        lo, hi = 0, len(obs) - 1
        if timestamp < obs[0].timestamp:
            return None
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if obs[mid].timestamp <= timestamp + 1e-9:
                lo = mid
            else:
                hi = mid - 1
        before = obs[lo]
        if abs(before.timestamp - timestamp) <= 1e-9:
            b = before.box
            return TrackPoint(
                self.track_id,
                timestamp,
                b.center_x,
                b.center_y,
                b.width,
                b.height,
                before.confidence,
                True,
            )
        if lo + 1 < len(obs) and obs[lo + 1].timestamp - before.timestamp <= max_gap + 1e-9:
            after = obs[lo + 1]
            f = (timestamp - before.timestamp) / (after.timestamp - before.timestamp)
            a, b = before.box, after.box
            return TrackPoint(
                self.track_id,
                timestamp,
                a.center_x + (b.center_x - a.center_x) * f,
                a.center_y + (b.center_y - a.center_y) * f,
                a.width + (b.width - a.width) * f,
                a.height + (b.height - a.height) * f,
                min(before.confidence, after.confidence),
                False,
            )
        gap = timestamp - before.timestamp
        if gap > max_gap:
            return None
        b = before.box
        decay = max(0.0, 1 - gap / max_gap)
        return TrackPoint(
            self.track_id,
            timestamp,
            b.center_x,
            b.center_y,
            b.width,
            b.height,
            before.confidence * decay,
            False,
        )


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    iw, ih = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def associate(
    frames: Sequence[tuple[float, Sequence[SubjectDetection]]],
    *,
    max_gap: float,
    sample_period: float,
) -> list[Track]:
    """Link detections over time into tracks (deterministic)."""
    tracks: list[Track] = []
    for timestamp, unordered in sorted(frames, key=lambda item: item[0]):
        # Position order, not detector output order, decides track ids: fully deterministic.
        detections = sorted(
            unordered, key=lambda d: (d.box.center_x, d.box.center_y, -d.confidence)
        )
        live = [
            t
            for t in tracks
            if timestamp - t.last_seen <= max_gap + 1e-9 and t.last_seen < timestamp
        ]
        pairs = []
        for track in live:
            predicted = track.predict(timestamp)
            gap_periods = max(1.0, (timestamp - track.last_seen) / sample_period)
            for index, det in enumerate(detections):
                box = (det.box.center_x, det.box.center_y, det.box.width, det.box.height)
                iou = _iou(predicted, box)
                scale = max(predicted[2], box[2], 1e-6)
                distance = math.hypot(box[0] - predicted[0], box[1] - predicted[1]) / scale
                areas = (predicted[2] * predicted[3], box[2] * box[3])
                ratio = min(areas) / max(areas) if max(areas) > 0 else 0.0
                if iou >= MIN_IOU or (
                    distance <= MAX_MATCH_DISTANCE * math.sqrt(gap_periods)
                    and ratio >= MIN_SIZE_RATIO
                ):
                    pairs.append((distance - iou, track.track_id, index, track))
        pairs.sort(key=lambda p: (p[0], p[1], p[2]))
        used_tracks: set[int] = set()
        used_dets: set[int] = set()
        for _cost, track_id, index, track in pairs:
            if track_id in used_tracks or index in used_dets:
                continue
            track.observations.append(detections[index])
            used_tracks.add(track_id)
            used_dets.add(index)
        for index, det in enumerate(detections):
            if index not in used_dets:
                tracks.append(Track(track_id=len(tracks), observations=[det]))
    return tracks


@dataclass(frozen=True)
class SubjectSample:
    """Who the crop should follow at one sampled moment, plus the other visible faces."""

    timestamp: float
    primary: TrackPoint | None
    others: tuple[TrackPoint, ...]
    cut: bool = False  # the subject was handed off to a face that appeared after it vanished


@dataclass(frozen=True)
class TrackingResult:
    tracks: list[Track]
    samples: list[SubjectSample]
    switches: int  # changes of subject between two different tracks (not losses/fallbacks)


def _scores(
    points: Sequence[TrackPoint], tracks: dict[int, Track], sample_period: float
) -> dict[int, float]:
    largest = max(tracks[p.track_id].average_area for p in points)
    scores = {}
    for p in points:
        track = tracks[p.track_id]
        size = track.average_area / largest if largest > 0 else 0.0
        persistence = min(1.0, track.observed_duration(sample_period) / PERSISTENCE_SECONDS)
        centrality = max(0.0, 1 - abs(p.center_x - 0.5) * 2)
        scores[p.track_id] = (
            WEIGHTS["size"] * size
            + WEIGHTS["persistence"] * persistence
            + WEIGHTS["confidence"] * p.confidence
            + WEIGHTS["centrality"] * centrality
        )
    return scores


def track_subjects(
    frames: Sequence[tuple[float, Sequence[SubjectDetection]]],
    *,
    max_gap: float,
    sample_period: float,
) -> TrackingResult:
    """Tracks, and the followed subject (with hysteresis) at every sampled timestamp."""
    tracks = associate(frames, max_gap=max_gap, sample_period=sample_period)
    eligible = {t.track_id: t for t in tracks if len(t.observations) >= MIN_OBSERVATIONS}
    samples: list[SubjectSample] = []
    current: int | None = None
    challenger: int | None = None
    challenger_since = 0.0
    switches = 0
    for timestamp in sorted(ts for ts, _ in frames):
        points = [
            p
            for t in eligible.values()
            if (p := t.point_at(timestamp, max_gap)) is not None and p.confidence > 0
        ]
        points.sort(key=lambda p: p.track_id)
        if not points:
            samples.append(SubjectSample(timestamp, None, ()))
            current, challenger = None, None
            continue
        scores = _scores(points, eligible, sample_period)
        # Ties (rare) go to the leftmost face, independent of detector output order.
        best = max(
            points, key=lambda p: (round(scores[p.track_id], 9), -p.center_x, -p.center_y)
        ).track_id
        visible = {p.track_id for p in points}
        previous = current
        if current in visible and timestamp > eligible[current].last_seen + 1e-9:
            # The subject has ended and is only held: a face that appeared after it was last
            # seen takes over now (a hand-off), rather than after the held box expires.
            ended = eligible[current].last_seen
            fresh = [p for p in points if eligible[p.track_id].first_seen > ended + 1e-9]
            if fresh:
                fresh_scores = {p.track_id: scores[p.track_id] for p in fresh}
                current = max(
                    fresh,
                    key=lambda p: (round(fresh_scores[p.track_id], 9), -p.center_x, -p.center_y),
                ).track_id
                challenger = None
                switches += 1
        if current not in visible:
            if current is not None and best != current:
                switches += 1
            current, challenger = best, None
        elif best != current and scores[best] > scores[current] * (1 + SWITCH_MARGIN):
            if challenger != best:
                challenger, challenger_since = best, timestamp
            if timestamp - challenger_since >= SWITCH_HOLD_SECONDS - 1e-9:
                current, challenger = best, None
                switches += 1
        else:
            challenger = None
        primary = next(p for p in points if p.track_id == current)
        others = tuple(p for p in points if p.track_id != current)
        cut = (
            previous is not None
            and current != previous
            and eligible[current].first_seen > eligible[previous].last_seen + 1e-9
        )
        samples.append(SubjectSample(timestamp, primary, others, cut))
    return TrackingResult(tracks=tracks, samples=samples, switches=switches)
