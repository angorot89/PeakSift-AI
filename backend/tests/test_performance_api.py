"""The performance API: owner-scoped, honest about access and simulation, NULL never shown as
zero, processed totals from one source, the refresh endpoint's grant check, cooldown and rate
limit, and nothing internal in any response."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.api import performance as api
from app.models import AnalyticsSync, PerformanceDailyMetric, PerformanceSnapshot
from app.services.performance.fake import FakeMetricsProvider
from app.services.performance.metrics import reporting_today
from app.services.performance.sync import request_sync, run_sync
from app.workers import dispatch
from tests.performance_fixtures import (
    NOW,
    analytics_settings,
    grant,
    make_content,
    signed_in_creator,
)
from tests.publishing_fixtures import REFRESH_TOKEN

PUBLISHED = NOW - timedelta(days=12)


@pytest.fixture
def settings(monkeypatch):
    configured = analytics_settings()
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr(dispatch, "enqueue_performance_sync",
                        lambda sync_id, *, task_id: calls.append(sync_id) or task_id)  # fmt: skip
    return calls


def synced(db, content, settings):
    fake = FakeMetricsProvider(today=lambda: reporting_today(NOW))
    fake.register(content.remote_video_id, reporting_today(content.published_at))
    sync = request_sync(db, content, "scheduled", settings)
    run_sync(sync.id, db, settings=settings, provider=fake, task_id=sync.celery_task_id, at=NOW)
    return fake


def test_signed_out_is_refused(client):
    client.cookies.clear()
    assert client.get("/performance").status_code == 401


def test_access_is_reported_honestly(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    body = client.get("/performance").json()
    assert body["access"] == {"enabled": True, "connected": False, "connection_status": None,
                              "analytics_access": False, "simulated": True}  # fmt: skip
    grant(db_session, user, analytics=False)
    assert client.get("/performance").json()["access"]["analytics_access"] is False
    grant(db_session, user)
    assert client.get("/performance").json()["access"]["analytics_access"] is True


def test_a_video_never_synced_shows_nothing_rather_than_zero(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    make_content(db_session, user, edit, published_at=PUBLISHED, provenance={"recipe": "manual"})
    [video] = client.get("/performance").json()["videos"]
    for field in (
        "views",
        "likes",
        "comments",
        "engaged_views",
        "average_view_percentage",
        "processed_through",
        "source",
        "counters_observed_at",
        "latest_sync",
    ):
        assert video[field] is None, field
    assert video["processed_days"] == 0 and video["recipe"] == "manual"


def test_synced_figures_are_labelled_and_summed_from_one_source(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    content = make_content(db_session, user, edit, published_at=PUBLISHED)
    synced(db_session, content, settings)
    [video] = client.get("/performance").json()["videos"]
    days = db_session.scalars(
        select(PerformanceDailyMetric).where(PerformanceDailyMetric.content_id == content.id)
    ).all()
    snapshot = db_session.scalar(select(PerformanceSnapshot))
    assert video["source"] == "fake" and video["simulated"] is True and video["video_url"] is None
    assert video["views"] == snapshot.views and video["likes"] == snapshot.likes
    assert video["engaged_views"] == sum(d.engaged_views for d in days)
    weighted = sum(d.average_view_percentage * d.views for d in days if d.views)
    assert video["average_view_percentage"] == round(weighted / sum(d.views for d in days), 1)
    assert video["processed_through"] == "2026-10-20" and video["processed_days"] == 11
    assert video["latest_sync"]["status"] == "completed"


def test_real_videos_link_to_youtube_unless_missing(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    content = make_content(db_session, user, edit, published_at=PUBLISHED,
                           remote_video_id="dQw4w9WgXcQ")  # fmt: skip
    db_session.add(PerformanceSnapshot(content_id=content.id, source="youtube",
                                       data_class="counters", observed_at=NOW, views=3,
                                       metric_version="youtube_views_2026_08"))  # fmt: skip
    db_session.commit()
    [video] = client.get("/performance").json()["videos"]
    assert video["video_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert video["simulated"] is False and video["likes"] is None  # not reported: null
    content.remote_status = "remote_missing"
    db_session.commit()
    assert client.get("/performance").json()["videos"][0]["video_url"] is None


def test_the_detail_shows_days_history_and_how_it_was_made(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    content = make_content(db_session, user, edit, published_at=PUBLISHED,
                           provenance={"recipe": "punchy", "layout": "smart_reframe"})  # fmt: skip
    synced(db_session, content, settings)
    response = client.get(f"/performance/videos/{content.id}")
    assert response.status_code == 200
    body = response.json()
    assert [d["date"] for d in body["daily"]][:2] == ["2026-10-10", "2026-10-11"]
    assert {d["metric_version"] for d in body["daily"]} == {"youtube_views_2026_08"}
    assert len(body["snapshots"]) == 1 and body["syncs"][0]["kind"] == "scheduled"
    assert body["provenance"] == {"recipe": "punchy", "layout": "smart_reframe"}
    text = response.text
    for internal in ("celery_task_id", content.syncs[0].celery_task_id, REFRESH_TOKEN,
                     "refresh_token", "scopes", "user_id"):  # fmt: skip
        assert internal not in text


def test_other_creators_videos_are_invisible(client, db_session, settings, queued):
    owner, edit = signed_in_creator(db_session, client)
    grant(db_session, owner)
    content = make_content(db_session, owner, edit, published_at=PUBLISHED)
    signed_in_creator(db_session, client)  # someone else signs in
    assert client.get("/performance").json()["videos"] == []
    assert client.get(f"/performance/videos/{content.id}").status_code == 404
    assert client.post(f"/performance/videos/{content.id}/refresh").status_code == 404
    assert queued == []


# --- refresh -----------------------------------------------------------------------------------


def test_refresh_needs_the_analytics_grant(client, db_session, settings, queued):
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user, analytics=False)
    content = make_content(db_session, user, edit, published_at=PUBLISHED)
    response = client.post(f"/performance/videos/{content.id}/refresh")
    assert response.status_code == 409 and "not connected" in response.json()["detail"]
    assert queued == []


def test_refresh_queues_once_then_cools_down(client, db_session, settings, queued):
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    content = make_content(db_session, user, edit, published_at=PUBLISHED)
    first = client.post(f"/performance/videos/{content.id}/refresh")
    assert first.status_code == 202 and first.json()["status"] == "queued"
    again = client.post(f"/performance/videos/{content.id}/refresh")
    assert again.status_code == 202 and len(queued) == 1  # the running one, not a second
    sync = db_session.get(AnalyticsSync, queued[0])
    sync.status, sync.completed_at = "completed", sync.created_at
    content.last_synced_at = sync.created_at
    db_session.commit()
    cooling = client.post(f"/performance/videos/{content.id}/refresh")
    assert cooling.status_code == 429 and 0 < int(cooling.headers["retry-after"]) <= 900


def test_refresh_is_refused_when_analytics_is_off(client, db_session, monkeypatch, queued):
    off = analytics_settings(youtube_analytics_enabled=False)
    monkeypatch.setattr(api, "get_settings", lambda: off)
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    content = make_content(db_session, user, edit, published_at=PUBLISHED)
    response = client.post(f"/performance/videos/{content.id}/refresh")
    assert response.status_code == 409 and client.get("/performance").json()["access"][
        "enabled"] is False  # fmt: skip


def test_refresh_is_rate_limited_per_creator(client, db_session, settings, monkeypatch):
    from app.core import rate_limit
    from app.core.rate_limit import DEFAULT_LIMITS, Limit, RateLimiter

    class Memory:
        counts: dict = {}

        def hit(self, key, window):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

    limiter = RateLimiter(Memory(), {**DEFAULT_LIMITS, "analytics_refresh": Limit(1, 3600)})
    monkeypatch.setattr(rate_limit, "get_limiter", lambda: limiter)
    user, edit = signed_in_creator(db_session, client)
    content = make_content(db_session, user, edit, published_at=PUBLISHED)
    codes = [client.post(f"/performance/videos/{content.id}/refresh").status_code
             for _ in range(2)]  # fmt: skip
    assert codes[1] == 429


def test_days_are_reported_per_view_definition(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    content = make_content(db_session, user, edit, published_at=PUBLISHED)
    db_session.add(
        PerformanceSnapshot(
            content_id=content.id,
            source="fake",
            data_class="counters",
            observed_at=NOW,
            metric_version="youtube_views_2026_08",
        )
    )
    for day, version in ((date(2026, 8, 26), "youtube_views_2025_03"),
                         (date(2026, 8, 27), "youtube_views_2026_08")):  # fmt: skip
        db_session.add(PerformanceDailyMetric(content_id=content.id, source="fake", date=day,
                                              metric_version=version, views=5))  # fmt: skip
    db_session.commit()
    daily = client.get(f"/performance/videos/{content.id}").json()["daily"]
    assert [(d["date"], d["metric_version"]) for d in daily] == [
        ("2026-08-26", "youtube_views_2025_03"),
        ("2026-08-27", "youtube_views_2026_08"),
    ]
    assert daily[0]["engaged_views"] is None  # not reported: null, not 0
