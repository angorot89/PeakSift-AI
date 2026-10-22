"""Comparable figures: fixed early windows, completeness, and the creator's own baseline.

Raw lifetime totals are not comparable — a short published yesterday has had less time than one
from last month — so comparisons use **the same early window for every short**, measured in
YouTube's reporting days (Pacific Time) starting with the day of publication:

- ``day_1`` — the day of publication (a partial day: it starts at the upload time, so it is
  roughly the first 24 hours, never exactly);
- ``day_3`` — the first three reporting days (≈ 72 hours);
- ``day_7`` — the first seven reporting days (≈ one week).

A window is **complete** only when every one of its days is settled (older than YouTube's 2–3
day processing delay) *and* reported for every figure used; **open** while any day is still
being processed; **incomplete** when settled days are missing. Only complete windows are
compared — a partial figure is never compared with a full one, and a missing day is never
counted as zero.

The primary comparison figure is **engaged views**, whose definition YouTube did not change;
``views`` is summed only when every day of the window uses the same view definition. Retention
(average % viewed) is weighted by each day's views.

The **baseline** is the creator's own median over their comparable shorts (complete window,
same data source — real and simulated data are never mixed), never other creators' data. Below
``MIN_SAMPLE`` comparable shorts there is **no reliable pattern yet**, and no position is given.
A short's position against the baseline leaves the short itself out of the median.
"""

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PerformanceDailyMetric, PublishedContent
from app.services.performance.metrics import reporting_today

WINDOWS = {"day_1": 1, "day_3": 3, "day_7": 7}
PRIMARY_WINDOW = "day_7"
MIN_SAMPLE = 5
# Within ±15% of the median reads as "near your usual" (medians of small samples are noisy).
NEAR_BAND = 0.15


@dataclass(frozen=True)
class Window:
    key: str
    days_expected: int
    days_reported: int
    status: str  # complete | open | incomplete
    engaged_views: int | None = None
    views: int | None = None
    average_view_percentage: float | None = None
    watch_time_seconds: float | None = None
    likes: int | None = None
    comments: int | None = None
    subscribers_gained: int | None = None

    @property
    def complete(self) -> bool:
        return self.status == "complete"


@dataclass(frozen=True)
class Baseline:
    metric: str
    window: str
    sample_size: int
    minimum_sample: int
    median: float | None

    @property
    def reliable(self) -> bool:
        return self.sample_size >= self.minimum_sample and self.median is not None


@dataclass(frozen=True)
class Position:
    value: float
    median: float
    ratio: float | None  # value / median (None when the median is 0)
    label: str  # above | near | below


def _sum_all(rows, field: str) -> int | float | None:
    """The window's total, only when every day reported the figure (else unknown)."""
    values = [getattr(row, field) for row in rows]
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def _weighted_retention(rows) -> float | None:
    pairs = [(r.average_view_percentage, r.views) for r in rows]
    if not pairs or any(p is None or v is None for p, v in pairs):
        return None
    weight = sum(v for _, v in pairs)
    if weight == 0:
        return None
    return round(sum(p * v for p, v in pairs) / weight, 1)


def window(rows, published_day: date, settled_through: date | None, key: str) -> Window:
    """One early window from a video's daily rows of one source."""
    days = WINDOWS[key]
    end = published_day + timedelta(days - 1)
    inside = sorted((r for r in rows if published_day <= r.date <= end), key=lambda r: r.date)
    if len({r.date for r in inside}) != len(inside):
        raise ValueError("one source, one row per day")
    if settled_through is None or end > settled_through:
        return Window(key, days, len(inside), "open")
    if len(inside) < days:
        return Window(key, days, len(inside), "incomplete")
    one_definition = len({r.metric_version for r in inside}) == 1
    figures = {
        "engaged_views": _sum_all(inside, "engaged_views"),
        "views": _sum_all(inside, "views") if one_definition else None,
        "average_view_percentage": _weighted_retention(inside),
        "watch_time_seconds": _sum_all(inside, "watch_time_seconds"),
        "likes": _sum_all(inside, "likes"),
        "comments": _sum_all(inside, "comments"),
        "subscribers_gained": _sum_all(inside, "subscribers_gained"),
    }
    # Complete means the comparison figure is known for every day, not just that rows exist.
    status = "complete" if figures["engaged_views"] is not None else "incomplete"
    return Window(key, days, len(inside), status, **figures)


def windows_for(rows, published_day: date, settled_through: date | None) -> dict[str, Window]:
    return {key: window(rows, published_day, settled_through, key) for key in WINDOWS}


def baseline(values: list[float], *, metric: str, window_key: str) -> Baseline:
    clean = [value for value in values if value is not None]
    median = statistics.median(clean) if clean else None
    return Baseline(metric, window_key, len(clean), MIN_SAMPLE, median)


def position(value: float | None, others: list[float]) -> Position | None:
    """Where ``value`` sits against the median of ``others`` (the short itself left out), or
    None without a reliable sample."""
    if value is None:
        return None
    sample = [other for other in others if other is not None]
    if len(sample) < MIN_SAMPLE:
        return None
    median = statistics.median(sample)
    ratio = value / median if median else None
    if ratio is None:
        label = "above" if value > 0 else "near"
    elif ratio > 1 + NEAR_BAND:
        label = "above"
    elif ratio < 1 - NEAR_BAND:
        label = "below"
    else:
        label = "near"
    return Position(value, median, round(ratio, 2) if ratio is not None else None, label)


# --- loading ----------------------------------------------------------------------------------


def published_day(content: PublishedContent) -> date:
    return reporting_today(content.published_at)


def load_windows(
    db: Session, contents: list[PublishedContent], sources: dict[uuid.UUID, str]
) -> dict[uuid.UUID, dict[str, Window]]:
    """Early windows of each video, from the daily rows of its current source."""
    wanted = [content for content in contents if content.id in sources]
    if not wanted:
        return {}
    rows = db.scalars(
        select(PerformanceDailyMetric).where(
            PerformanceDailyMetric.content_id.in_([c.id for c in wanted])
        )
    ).all()
    by_content: dict[uuid.UUID, list] = defaultdict(list)
    for row in rows:
        if sources[row.content_id] == row.source:
            by_content[row.content_id].append(row)
    return {
        content.id: windows_for(
            by_content[content.id], published_day(content), content.analytics_complete_through
        )
        for content in wanted
    }


# Figures compared against the creator's baseline, on the primary window.
COMPARED = ("engaged_views", "average_view_percentage")


@dataclass(frozen=True)
class Comparisons:
    windows: dict[uuid.UUID, dict[str, Window]]
    positions: dict[uuid.UUID, dict[str, Position]]
    baselines: list[Baseline]
    source: str


def compare(
    db: Session, contents: list[PublishedContent], sources: dict[uuid.UUID, str], source: str
) -> Comparisons:
    """Windows for every video; baselines and positions among the videos of ``source`` whose
    primary window is complete. Never anything from another creator: ``contents`` is one
    creator's videos."""
    windows = load_windows(db, contents, sources)
    comparable = {
        content_id: found[PRIMARY_WINDOW]
        for content_id, found in windows.items()
        if sources.get(content_id) == source and found[PRIMARY_WINDOW].complete
    }
    baselines = [
        baseline([getattr(w, metric) for w in comparable.values()], metric=metric,
                 window_key=PRIMARY_WINDOW)
        for metric in COMPARED
    ]  # fmt: skip
    positions: dict[uuid.UUID, dict[str, Position]] = {}
    for content_id, own in comparable.items():
        found = {}
        for metric in COMPARED:
            others = [getattr(w, metric) for other, w in comparable.items() if other != content_id]
            placed = position(getattr(own, metric), others)
            if placed is not None:
                found[metric] = placed
        positions[content_id] = found
    return Comparisons(windows, positions, baselines, source)
