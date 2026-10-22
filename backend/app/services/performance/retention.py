"""Deleting the metrics PeakSift collected for a creator, on request.

Removes every snapshot, daily row, sync record and insight set of the creator's published
shorts, and stops scheduled syncs. The published-content links themselves (which PeakSift output
became which video, and how it was made) stay: they are publishing records, and without metrics
they show nothing. Syncing starts again only when the creator refreshes a short or grants
analytics access again. Disconnecting YouTube is separate (Settings) and removes the grant.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import (
    AnalyticsSync,
    InsightSet,
    PerformanceDailyMetric,
    PerformanceSnapshot,
    PublishedContent,
    RemoteStatus,
)


@dataclass(frozen=True)
class Deleted:
    snapshots: int
    days: int
    syncs: int
    insight_sets: int


def delete_collected(db: Session, user_id: uuid.UUID) -> Deleted:
    contents = select(PublishedContent.id).where(PublishedContent.user_id == user_id)
    counts = [
        db.execute(delete(model).where(model.content_id.in_(contents))).rowcount
        for model in (PerformanceSnapshot, PerformanceDailyMetric, AnalyticsSync)
    ]
    sets = db.execute(delete(InsightSet).where(InsightSet.user_id == user_id)).rowcount
    db.execute(
        update(PublishedContent)
        .where(PublishedContent.user_id == user_id)
        .values(last_synced_at=None, next_sync_at=None, analytics_complete_through=None,
                remote_status=RemoteStatus.UNKNOWN)
    )  # fmt: skip
    db.commit()
    return Deleted(*counts, sets)
