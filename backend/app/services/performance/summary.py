"""What a creator sees about a published video: the latest counters and processed totals.

Every figure is computed from stored rows of **one source** (the latest snapshot's: ``youtube``,
or ``fake`` for simulated data) and returned as ``None`` when nothing was reported — never 0:

- ``views`` / ``likes`` / ``comments``: the latest live counters (the platform's current
  public figures, under its current view definition);
- ``engaged_views``: the sum of processed daily engaged views (a definition YouTube did not
  change), ``None`` when no day reported it;
- ``average_view_percentage``: daily averages weighted by that day's views (days where both are
  reported); retention above 100% is possible for replayed Shorts and is kept;
- ``processed_through``: the last processed reporting day stored.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from app.models import AnalyticsSync, PerformanceDailyMetric, PerformanceSnapshot, PublishedContent


@dataclass(frozen=True)
class Counters:
    source: str
    observed_at: datetime
    views: int | None
    likes: int | None
    comments: int | None


@dataclass(frozen=True)
class Processed:
    engaged_views: int | None
    average_view_percentage: float | None
    processed_through: date | None
    days: int


def latest_counters(db: Session, content_ids: list[uuid.UUID]) -> dict[uuid.UUID, Counters]:
    if not content_ids:
        return {}
    ranked = (
        select(
            PerformanceSnapshot,
            func.row_number()
            .over(
                partition_by=PerformanceSnapshot.content_id,
                order_by=(PerformanceSnapshot.observed_at.desc(), PerformanceSnapshot.id.desc()),
            )
            .label("rank"),
        )
        .where(PerformanceSnapshot.content_id.in_(content_ids))
        .subquery()
    )
    rows = db.execute(select(ranked).where(ranked.c.rank == 1)).all()
    return {
        row.content_id: Counters(row.source, row.observed_at, row.views, row.likes, row.comments)
        for row in rows
    }


def processed_totals(db: Session, sources: dict[uuid.UUID, str]) -> dict[uuid.UUID, Processed]:
    """Per video, over the daily rows of the given source."""
    if not sources:
        return {}
    daily = PerformanceDailyMetric
    weighted = case(
        (
            (daily.views > 0) & daily.average_view_percentage.is_not(None),
            daily.average_view_percentage * cast(daily.views, Float),
        ),
    )
    weight = case(
        ((daily.views > 0) & daily.average_view_percentage.is_not(None), daily.views),
    )
    rows = db.execute(
        select(
            daily.content_id,
            daily.source,
            func.sum(daily.engaged_views),
            func.sum(weighted),
            func.sum(weight),
            func.max(daily.date),
            func.count(),
        )
        .where(daily.content_id.in_(list(sources)))
        .group_by(daily.content_id, daily.source)
    ).all()
    result = {}
    for content_id, source, engaged, weighted_sum, weight_sum, through, days in rows:
        if sources[content_id] != source:
            continue
        retention = float(weighted_sum) / float(weight_sum) if weight_sum else None
        result[content_id] = Processed(
            engaged_views=int(engaged) if engaged is not None else None,
            average_view_percentage=round(retention, 1) if retention is not None else None,
            processed_through=through,
            days=days,
        )
    return result


def latest_syncs(db: Session, content_ids: list[uuid.UUID]) -> dict[uuid.UUID, AnalyticsSync]:
    if not content_ids:
        return {}
    ranked = (
        select(
            AnalyticsSync.id,
            func.row_number()
            .over(
                partition_by=AnalyticsSync.content_id,
                order_by=(AnalyticsSync.created_at.desc(), AnalyticsSync.id.desc()),
            )
            .label("rank"),
        )
        .where(AnalyticsSync.content_id.in_(content_ids))
        .subquery()
    )
    ids = db.scalars(select(ranked.c.id).where(ranked.c.rank == 1)).all()
    syncs = db.scalars(select(AnalyticsSync).where(AnalyticsSync.id.in_(ids))).all()
    return {sync.content_id: sync for sync in syncs}


def user_contents(db: Session, user_id: uuid.UUID, limit: int = 200) -> list[PublishedContent]:
    return list(
        db.scalars(
            select(PublishedContent)
            .where(PublishedContent.user_id == user_id)
            .order_by(PublishedContent.published_at.desc(), PublishedContent.id)
            .limit(limit)
        )
    )
