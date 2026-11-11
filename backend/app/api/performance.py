"""Performance analytics for the signed-in creator's published shorts.

- ``GET /performance`` — analytics access (server switch, connection, the read-only grant,
  simulated or real) and every PeakSift-published video with its latest counters and
  processed totals, newest first.
- ``GET /performance/videos/{content_id}`` — one video: daily processed rows (with the view
  definition of each day), counter history, recent syncs and how the short was made.
- ``POST /performance/videos/{content_id}/refresh`` — ask for a sync now: ``202`` with the
  sync; ``409`` without the analytics grant (or with analytics off); ``429`` with
  ``Retry-After`` right after a sync, or when the per-creator budget is spent.
- ``GET /performance/insights`` — observed patterns among the creator's own comparable shorts
  (``services/performance/insights.py``), recomputed only when the data changed; dismissed ones
  are included with ``dismissed: true``.
- ``POST /performance/insights/{id}/dismiss`` and ``…/restore`` — hide or show one again.
- ``DELETE /performance/data`` — delete every metric PeakSift collected for this creator (and
  their insights) and stop scheduled syncs (``services/performance/retention.py``).

Everything is owner-scoped (``404`` for anyone else). Figures are what the platform reported;
``null`` is "not reported", never zero. Responses never contain tokens, task ids or provider
payloads, and never other creators' data.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import AnalyticsSync, PerformanceDailyMetric, PerformanceSnapshot, PublishedContent
from app.schemas.performance import (
    AnalyticsAccessRead,
    BaselineRead,
    CollectedDataDeletedRead,
    DailyMetricRead,
    EvidenceShortRead,
    InsightRead,
    InsightsRead,
    PerformanceOverviewRead,
    SnapshotRead,
    SyncRead,
    VideoPerformanceDetailRead,
    VideoPerformanceRead,
)
from app.services.performance import insights as insight_engine
from app.services.performance import normalization, summary
from app.services.performance.lifecycle import start_manual_sync
from app.services.performance.retention import delete_collected
from app.services.performance.sync import RefreshTooSoon, has_analytics_grant
from app.services.publishing import connections

router = APIRouter(prefix="/performance", tags=["performance"])

DETAIL_SNAPSHOTS = 60
DETAIL_SYNCS = 10


def analytics_access(db, user_id: uuid.UUID) -> AnalyticsAccessRead:
    """Whether this creator's analytics can be shown (server switch, connection, the read-only
    grant) and whether figures are simulated. Shared with the Short's page."""
    settings = get_settings()
    connection = connections.get_connection(db, user_id)
    return AnalyticsAccessRead(
        enabled=settings.youtube_publishing_enabled and settings.youtube_analytics_enabled,
        connected=connection is not None,
        connection_status=connection.status if connection else None,
        analytics_access=has_analytics_grant(connection),
        simulated=settings.performance_provider == "fake",
    )


def _sync_read(sync: AnalyticsSync | None) -> SyncRead | None:
    if sync is None:
        return None
    return SyncRead(
        kind=sync.kind, status=sync.status, error_code=sync.error_code,
        error_message=sync.error_message, created_at=sync.created_at,
        completed_at=sync.completed_at,
    )  # fmt: skip


def _video(content, counters, processed, sync) -> dict:
    source = counters.source if counters else None
    real = source == "youtube"
    return {
        "id": content.id, "project_id": content.project_id, "edit_id": content.edit_id,
        "title": content.title, "published_at": content.published_at,
        "duration_seconds": content.duration_seconds, "privacy": content.privacy,
        "remote_status": content.remote_status, "source": source, "simulated": source == "fake",
        "video_url": f"https://www.youtube.com/watch?v={content.remote_video_id}"
        if real and content.remote_status != "remote_missing" else None,
        "views": counters.views if counters else None,
        "likes": counters.likes if counters else None,
        "comments": counters.comments if counters else None,
        "counters_observed_at": counters.observed_at if counters else None,
        "engaged_views": processed.engaged_views if processed else None,
        "average_view_percentage": processed.average_view_percentage if processed else None,
        "processed_through": processed.processed_through if processed else None,
        "processed_days": processed.days if processed else 0,
        "last_synced_at": content.last_synced_at, "next_sync_at": content.next_sync_at,
        "latest_sync": _sync_read(sync), "recipe": (content.provenance or {}).get("recipe"),
    }  # fmt: skip


def _summaries(db, contents: list[PublishedContent], comparisons=None) -> list[dict]:
    ids = [content.id for content in contents]
    counters = summary.latest_counters(db, ids)
    sources = {i: c.source for i, c in counters.items()}
    processed = summary.processed_totals(db, sources)
    syncs = summary.latest_syncs(db, ids)
    videos = []
    for content in contents:
        video = _video(content, counters.get(content.id), processed.get(content.id),
                       syncs.get(content.id))  # fmt: skip
        if comparisons is not None:
            video["windows"] = [vars(w) for w in comparisons.windows.get(content.id, {}).values()]
            video["positions"] = [
                {"metric": metric, "window": normalization.PRIMARY_WINDOW, **vars(placed)}
                for metric, placed in comparisons.positions.get(content.id, {}).items()
            ]
        videos.append(video)
    return videos


def _comparisons(db, user_id: uuid.UUID) -> normalization.Comparisons:
    """Every comparison is among this creator's own shorts, of the server's current source."""
    contents = summary.user_contents(db, user_id)
    counters = summary.latest_counters(db, [content.id for content in contents])
    source = "fake" if get_settings().performance_provider == "fake" else "youtube"
    return normalization.compare(db, contents, {i: c.source for i, c in counters.items()}, source)


def _owned(db, content_id: uuid.UUID, user_id: uuid.UUID) -> PublishedContent:
    content = db.scalar(
        select(PublishedContent).where(
            PublishedContent.id == content_id, PublishedContent.user_id == user_id
        )
    )
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return content


@router.get("", response_model=PerformanceOverviewRead)
def performance_overview(current_user: CurrentUser, db: DbSession) -> PerformanceOverviewRead:
    contents = summary.user_contents(db, current_user.id)
    comparisons = _comparisons(db, current_user.id)
    return PerformanceOverviewRead(
        access=analytics_access(db, current_user.id),
        videos=[VideoPerformanceRead(**v) for v in _summaries(db, contents, comparisons)],
        baselines=[BaselineRead(**vars(b), reliable=b.reliable) for b in comparisons.baselines],
    )


@router.get("/videos/{content_id}", response_model=VideoPerformanceDetailRead)
def video_performance(
    content_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> VideoPerformanceDetailRead:
    content = _owned(db, content_id, current_user.id)
    [video] = _summaries(db, [content], _comparisons(db, current_user.id))
    source = video["source"]
    daily = db.scalars(
        select(PerformanceDailyMetric)
        .where(PerformanceDailyMetric.content_id == content.id,
               PerformanceDailyMetric.source == source)
        .order_by(PerformanceDailyMetric.date, PerformanceDailyMetric.metric_version)
    ).all()  # fmt: skip
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.content_id == content.id, PerformanceSnapshot.source == source)
        .order_by(PerformanceSnapshot.observed_at.desc())
        .limit(DETAIL_SNAPSHOTS)
    ).all()
    syncs = db.scalars(
        select(AnalyticsSync)
        .where(AnalyticsSync.content_id == content.id)
        .order_by(AnalyticsSync.created_at.desc())
        .limit(DETAIL_SYNCS)
    ).all()
    return VideoPerformanceDetailRead(
        **video,
        provenance=content.provenance or {},
        daily=[DailyMetricRead.model_validate(row, from_attributes=True) for row in daily],
        snapshots=[
            SnapshotRead.model_validate(s, from_attributes=True) for s in reversed(snapshots)
        ],
        syncs=[_sync_read(sync) for sync in syncs],
    )


@router.post(
    "/videos/{content_id}/refresh",
    response_model=SyncRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[per_user("analytics_refresh")],
)
def refresh_video_performance(content_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    content = _owned(db, content_id, current_user.id)
    settings = get_settings()
    access = analytics_access(db, current_user.id)
    if not access.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Analytics is not enabled on this server"
        )
    if not access.analytics_access:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Analytics access is not connected")
    try:
        sync = start_manual_sync(db, content, settings)
    except RefreshTooSoon as wait:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Metrics were refreshed moments ago; try again shortly"},
            headers={"Retry-After": str(wait.retry_after_seconds)},
        )
    if sync is None:  # one is already running: report it
        sync = summary.latest_syncs(db, [content.id]).get(content.id)
    return _sync_read(sync)


# --- insights ----------------------------------------------------------------------------------


def _current_source() -> str:
    return "fake" if get_settings().performance_provider == "fake" else "youtube"


def _insight_read(insight, titles: dict[str, str]) -> InsightRead:
    def shorts(ids: list[str]) -> list[EvidenceShortRead]:
        # Only the creator's own shorts that still exist are named.
        return [EvidenceShortRead(id=uuid.UUID(i), title=titles[i]) for i in ids if i in titles]

    return InsightRead(
        id=insight.id, rank=insight.rank, feature=insight.feature, value=insight.value,
        metric=insight.metric, window=insight.window, direction=insight.direction,
        group_size=insight.group_size, comparison_size=insight.comparison_size,
        group_median=insight.group_median, comparison_median=insight.comparison_median,
        ratio=insight.ratio, consistency=insight.consistency, confidence=insight.confidence,
        statement=insight.statement, dismissed=insight.dismissed_at is not None,
        group=shorts(insight.evidence.get("group", [])),
        comparison=shorts(insight.evidence.get("comparison", [])),
    )  # fmt: skip


def _insights_read(db, user_id: uuid.UUID, insight_set) -> InsightsRead:
    titles = {str(c.id): c.title for c in summary.user_contents(db, user_id)}
    return InsightsRead(
        status=insight_set.status, source=insight_set.source,
        simulated=insight_set.source == "fake", engine_version=insight_set.engine_version,
        computed_at=insight_set.computed_at, sample_size=insight_set.sample_size,
        minimum_sample=insight_engine.MIN_SAMPLE, minimum_group=insight_engine.MIN_GROUP,
        insights=[_insight_read(i, titles) for i in insight_set.insights],
    )  # fmt: skip


@router.get("/insights", response_model=InsightsRead)
def creator_insights(current_user: CurrentUser, db: DbSession) -> InsightsRead:
    insight_set = insight_engine.ensure_insights(db, current_user.id, _current_source())
    return _insights_read(db, current_user.id, insight_set)


def _set_dismissed(db, insight_id: uuid.UUID, user_id: uuid.UUID, dismissed: bool):
    insight = insight_engine.owned_insight(db, insight_id, user_id)
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    insight.dismissed_at = insight_engine.now() if dismissed else None
    db.commit()
    titles = {str(c.id): c.title for c in summary.user_contents(db, user_id)}
    return _insight_read(insight, titles)


@router.post("/insights/{insight_id}/dismiss", response_model=InsightRead)
def dismiss_insight(insight_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return _set_dismissed(db, insight_id, current_user.id, True)


@router.post("/insights/{insight_id}/restore", response_model=InsightRead)
def restore_insight(insight_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return _set_dismissed(db, insight_id, current_user.id, False)


@router.delete("/data", response_model=CollectedDataDeletedRead)
def delete_collected_data(current_user: CurrentUser, db: DbSession) -> CollectedDataDeletedRead:
    deleted = delete_collected(db, current_user.id)
    return CollectedDataDeletedRead(**vars(deleted))
