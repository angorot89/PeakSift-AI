"""Comparable figures: early windows in reporting days (complete, open or incomplete — a missing
day or figure is never zero), one view definition per summed window, retention weighted by
views, and the creator's own median baseline with a minimum sample, leaving the short itself
out. Only one creator's shorts and one data source are ever compared."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.performance.fake import FakeMetricsProvider
from app.services.performance.metrics import reporting_today
from app.services.performance.normalization import (
    MIN_SAMPLE,
    baseline,
    position,
    window,
    windows_for,
)
from app.services.performance.sync import request_sync, run_sync
from tests.performance_fixtures import (
    NOW,
    analytics_settings,
    grant,
    make_content,
    signed_in_creator,
)

D0 = date(2026, 10, 1)
V26 = "youtube_views_2026_08"


def day(n, views=100, engaged=80, pct=50.0, version=V26, **kw):
    fields = {"likes": 5, "comments": 1, "watch_time_seconds": 900.0, "subscribers_gained": 0}
    return SimpleNamespace(date=D0 + timedelta(n), views=views, engaged_views=engaged,
                           average_view_percentage=pct, metric_version=version,
                           **{**fields, **kw})  # fmt: skip


SEVEN = [day(n) for n in range(7)]


# --- windows -----------------------------------------------------------------------------------


def test_a_complete_week_sums_every_day():
    w = window(SEVEN, D0, D0 + timedelta(10), "day_7")
    assert w.status == "complete" and w.days_reported == 7
    assert (w.engaged_views, w.views, w.likes, w.comments) == (560, 700, 35, 7)
    assert w.average_view_percentage == 50.0


def test_day_one_is_the_day_of_publication_only():
    w = window(SEVEN, D0, D0 + timedelta(10), "day_1")
    assert w.complete and w.engaged_views == 80 and w.days_expected == 1


def test_a_window_still_being_processed_is_open_without_figures():
    w = window(SEVEN[:5], D0, D0 + timedelta(4), "day_7")
    assert w.status == "open" and w.engaged_views is None and w.days_reported == 5
    assert window(SEVEN, D0, None, "day_1").status == "open"  # nothing settled yet


def test_a_settled_but_missing_day_makes_the_window_incomplete_never_zero():
    rows = [r for r in SEVEN if r.date != D0 + timedelta(3)]
    w = window(rows, D0, D0 + timedelta(10), "day_7")
    assert w.status == "incomplete" and w.engaged_views is None and w.days_reported == 6


def test_an_unreported_figure_on_one_day_leaves_that_total_unknown():
    rows = [*SEVEN[:6], day(6, likes=None)]
    w = window(rows, D0, D0 + timedelta(10), "day_7")
    assert w.complete and w.likes is None and w.engaged_views == 560
    no_engaged = [*SEVEN[:6], day(6, engaged=None)]
    assert window(no_engaged, D0, D0 + timedelta(10), "day_7").status == "incomplete"


def test_views_are_not_summed_across_view_definitions():
    rows = [day(n, version="youtube_views_2025_03" if n < 3 else V26) for n in range(7)]
    w = window(rows, D0, D0 + timedelta(10), "day_7")
    assert w.complete and w.views is None and w.engaged_views == 560  # engaged: one definition


def test_retention_is_weighted_by_views_and_may_exceed_100():
    rows = [day(0, views=300, pct=120.0), day(1, views=100, pct=40.0), day(2, views=0, pct=0.0)]
    w = window(rows, D0, D0 + timedelta(10), "day_3")
    assert w.average_view_percentage == 100.0  # (300·120 + 100·40) / 400


def test_rows_after_the_window_are_ignored():
    rows = [*SEVEN, day(7, engaged=10_000)]
    assert windows_for(rows, D0, D0 + timedelta(10))["day_7"].engaged_views == 560


# --- baseline and position ---------------------------------------------------------------------


def test_the_baseline_is_a_median_with_a_minimum_sample():
    b = baseline([10, 20, 30, 40, 1000], metric="engaged_views", window_key="day_7")
    assert b.median == 30 and b.sample_size == 5 and b.reliable  # a median resists the outlier
    small = baseline([10, 20, 30, 40, None], metric="engaged_views", window_key="day_7")
    assert small.sample_size == 4 and not small.reliable
    assert not baseline([], metric="engaged_views", window_key="day_7").reliable


@pytest.mark.parametrize(
    ("value", "label", "ratio"),
    [(300, "above", 3.0), (110, "near", 1.1), (90, "near", 0.9), (50, "below", 0.5)],
)
def test_positions_against_the_median(value, label, ratio):
    placed = position(value, [80, 90, 100, 110, 120])
    assert (placed.label, placed.ratio, placed.median) == (label, ratio, 100)


def test_no_position_without_a_reliable_sample():
    assert position(300, [100] * (MIN_SAMPLE - 1)) is None
    assert position(None, [100] * 10) is None
    assert position(5, [0] * 5).label == "above" and position(5, [0] * 5).ratio is None


# --- comparisons through the API ---------------------------------------------------------------


@pytest.fixture
def settings(monkeypatch):
    from app.api import performance as api

    configured = analytics_settings()
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


def publish_many(db, user, edit, settings, scales):
    """Shorts published 10–20 days ago, synced through the deterministic fake."""
    fake = FakeMetricsProvider(today=lambda: reporting_today(NOW))
    contents = []
    for n, scale in enumerate(scales):
        published = NOW - timedelta(days=10 + n)
        content = make_content(db, user, edit, published_at=published)
        fake.register(content.remote_video_id, reporting_today(published), scale=scale)
        sync = request_sync(db, content, "scheduled", settings)
        run_sync(sync.id, db, settings=settings, provider=fake, task_id=sync.celery_task_id,
                 at=NOW)  # fmt: skip
        contents.append(content)
    return contents


def test_the_overview_compares_complete_weeks_against_the_creators_median(client, db_session,
                                                                          settings):  # fmt: skip
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    contents = publish_many(db_session, user, edit, settings, [1, 1, 1, 1, 1, 8])
    body = client.get("/performance").json()
    engaged = next(b for b in body["baselines"] if b["metric"] == "engaged_views")
    assert engaged["sample_size"] == 6 and engaged["reliable"] and engaged["window"] == "day_7"
    by_id = {v["id"]: v for v in body["videos"]}
    big = by_id[str(contents[-1].id)]
    [placed] = [p for p in big["positions"] if p["metric"] == "engaged_views"]
    assert placed["label"] == "above" and placed["ratio"] > 1.15
    week = next(w for w in big["windows"] if w["key"] == "day_7")
    assert week["status"] == "complete" and week["engaged_views"] == placed["value"]
    assert placed["median"] != engaged["median"]  # leave-one-out: not its own median


def test_no_reliable_pattern_below_the_minimum_sample(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    publish_many(db_session, user, edit, settings, [1, 1, 1, 8])
    body = client.get("/performance").json()
    assert all(not b["reliable"] and b["sample_size"] == 4 for b in body["baselines"])
    assert all(v["positions"] == [] for v in body["videos"])


def test_recent_shorts_have_open_windows_and_are_left_out(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    fake = FakeMetricsProvider(today=lambda: reporting_today(NOW))
    content = make_content(db_session, user, edit, published_at=NOW - timedelta(days=4))
    fake.register(content.remote_video_id, reporting_today(content.published_at))
    sync = request_sync(db_session, content, "scheduled", settings)
    run_sync(sync.id, db_session, settings=settings, provider=fake, task_id=sync.celery_task_id,
             at=NOW)  # fmt: skip
    [video] = client.get("/performance").json()["videos"]
    statuses = {w["key"]: w["status"] for w in video["windows"]}
    assert statuses == {"day_1": "complete", "day_3": "open", "day_7": "open"}
    assert client.get("/performance").json()["baselines"][0]["sample_size"] == 0


def test_another_creators_shorts_never_enter_the_baseline(client, db_session, settings):
    other, other_edit = signed_in_creator(db_session, client)
    grant(db_session, other)
    publish_many(db_session, other, other_edit, settings, [1] * 6)
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    publish_many(db_session, user, edit, settings, [1, 1])
    body = client.get("/performance").json()
    assert body["baselines"][0]["sample_size"] == 2 and len(body["videos"]) == 2


def test_real_and_simulated_data_are_never_compared(client, db_session, settings):
    from app.models import PerformanceSnapshot

    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    contents = publish_many(db_session, user, edit, settings, [1] * 5)
    # One short whose latest data came from YouTube: a different source, left out.
    db_session.add(PerformanceSnapshot(content_id=contents[0].id, source="youtube",
                                       data_class="counters", observed_at=NOW + timedelta(1),
                                       metric_version=V26, views=1))  # fmt: skip
    db_session.commit()
    body = client.get("/performance").json()
    assert body["baselines"][0]["sample_size"] == 4 and not body["baselines"][0]["reliable"]
