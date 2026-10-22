# ruff: noqa: F811 - the google fixture imported from test_youtube_oauth is a parameter here
"""Syncing a published video's metrics: snapshots and daily rows labelled by source, NULL kept,
re-reading recent days without duplicates, missing videos, the grant checked on every run,
fencing, one active sync per video, failures and backoff, the bounded schedule and the
backfill of PeakSift's own earlier uploads. No network: the deterministic fake provider."""

from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select, text

from app.models import (
    AnalyticsSync,
    PerformanceDailyMetric,
    PerformanceSnapshot,
    PublishedContent,
    User,
)
from app.services.performance import lifecycle
from app.services.performance import sync as syncing
from app.services.performance.fake import FakeMetricsProvider
from app.services.performance.metrics import reporting_today
from app.services.performance.provider import PerformanceErrorCode
from app.services.performance.sync import (
    RefreshTooSoon,
    next_sync_after,
    request_manual_sync,
    request_sync,
    run_sync,
)
from app.services.publishing.connections import get_connection
from app.workers import dispatch
from tests.performance_fixtures import NOW, analytics_settings, creator, grant, make_content
from tests.publishing_fixtures import REFRESH_TOKEN
from tests.test_performance_domain import content_of, published
from tests.test_youtube_oauth import google  # noqa: F401 - fixture

PUBLISHED = NOW - timedelta(days=12)  # reporting day 2026-10-10
TODAY = reporting_today(NOW)  # 2026-10-22


@pytest.fixture
def settings():
    return analytics_settings()


@pytest.fixture
def fake():
    return FakeMetricsProvider(today=lambda: TODAY)


@pytest.fixture
def video(db_session, fake):
    user, edit = creator(db_session)
    grant(db_session, user)
    content = make_content(db_session, user, edit, published_at=PUBLISHED)
    fake.register(content.remote_video_id, reporting_today(PUBLISHED))
    return content


def run(db, content, settings, fake, *, at=NOW, kind="scheduled"):
    sync = request_sync(db, content, kind, settings)
    assert sync is not None
    return run_sync(sync.id, db, settings=settings, provider=fake, task_id=sync.celery_task_id,
                    at=at)  # fmt: skip


def days_of(db, content):
    return db.scalars(
        select(PerformanceDailyMetric)
        .where(PerformanceDailyMetric.content_id == content.id)
        .order_by(PerformanceDailyMetric.date)
    ).all()


# --- a sync ------------------------------------------------------------------------------------


def test_a_sync_stores_a_labelled_snapshot_and_one_row_per_day(db_session, video, settings, fake):
    sync = run(db_session, video, settings, fake)
    assert sync.status == "completed" and sync.error_code is None
    [snapshot] = video.snapshots
    assert snapshot.source == "fake" and snapshot.data_class == "counters"  # simulated: labelled
    assert snapshot.views > 0 and snapshot.observed_at == NOW
    days = days_of(db_session, video)
    # From the reporting day of publication to the last processed day (two days ago).
    assert [d.date for d in days] == [date(2026, 10, 10) + timedelta(n) for n in range(11)]
    assert {d.source for d in days} == {"fake"}
    assert {d.metric_version for d in days} == {"youtube_views_2026_08"}
    assert sync.days_upserted == 11 and sync.data_through == date(2026, 10, 20)
    assert video.remote_status == "active" and video.last_synced_at == NOW
    assert video.analytics_complete_through == date(2026, 10, 19)  # settled: three days back
    assert video.next_sync_at == NOW + timedelta(days=1)  # 12 days old: daily


def test_the_next_sync_re_reads_recent_days_without_duplicates(db_session, video, settings, fake):
    run(db_session, video, settings, fake)
    first = {d.date: d.views for d in days_of(db_session, video)}
    later = NOW + timedelta(days=1)
    fake.today = lambda: TODAY + timedelta(days=1)
    sync = run(db_session, video, settings, fake, at=later)
    # From three days before the settled day (2026-10-16) to the newly processed 2026-10-21.
    assert sync.days_upserted == 6
    days = days_of(db_session, video)
    assert len(days) == 12 and len({d.date for d in days}) == 12
    assert {d.date: d.views for d in days if d.date in first} == first
    assert len(video.snapshots) == 2


def test_unreported_metrics_stay_null(db_session, video, settings, fake):
    fake.videos[video.remote_video_id].hide_likes = True
    run(db_session, video, settings, fake)
    assert video.snapshots[0].likes is None and video.snapshots[0].views is not None
    assert all(d.likes is None and d.views is not None for d in days_of(db_session, video))


def test_view_definitions_are_recorded_per_day(db_session, settings, fake):
    user, edit = creator(db_session)
    grant(db_session, user)
    published = NOW.replace(year=2026, month=8, day=24)
    content = make_content(db_session, user, edit, published_at=published)
    fake.register(content.remote_video_id, date(2026, 8, 24))
    run(db_session, content, settings, fake, at=published + timedelta(days=6))
    versions = {d.date: d.metric_version for d in days_of(db_session, content)}
    assert versions[date(2026, 8, 26)] == "youtube_views_2025_03"
    assert versions[date(2026, 8, 27)] == "youtube_views_2026_08"


def test_a_video_gone_from_the_platform_is_marked_and_its_history_kept(db_session, video,
                                                                       settings, fake):  # fmt: skip
    run(db_session, video, settings, fake)
    fake.delete(video.remote_video_id)
    first = run(db_session, video, settings, fake, at=NOW + timedelta(hours=1), kind="manual")
    # One miss could be a momentary inconsistency: checked again a day later.
    assert first.status == "completed" and first.days_upserted == 0
    assert video.remote_status == "unknown"
    assert video.next_sync_at == NOW + timedelta(hours=25)
    run(db_session, video, settings, fake, at=NOW + timedelta(hours=25))
    assert video.remote_status == "remote_missing" and video.next_sync_at is None
    assert len(days_of(db_session, video)) == 11  # nothing deleted, nothing zeroed
    assert len(video.snapshots) == 1  # no "0 views" snapshot for a missing video


def test_a_video_that_comes_back_after_one_miss_is_active_again(db_session, video, settings,
                                                                fake):  # fmt: skip
    run(db_session, video, settings, fake)
    original = fake.video_counters
    fake.video_counters = lambda auth, ids: {}
    run(db_session, video, settings, fake, at=NOW + timedelta(hours=1), kind="manual")
    assert video.remote_status == "unknown"
    fake.video_counters = original
    run(db_session, video, settings, fake, at=NOW + timedelta(hours=25))
    assert video.remote_status == "active" and video.next_sync_at is not None


# --- the grant ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        (lambda db, user: grant(db, user, analytics=False), "analytics_not_connected"),
        (lambda db, user: setattr(grant(db, user), "status", "needs_reconnect"),
         "reconnect_required"),
        (lambda db, user: db.delete(grant(db, user)), "not_connected"),
    ],
    ids=["upload-only", "needs-reconnect", "disconnected"],
)  # fmt: skip
def test_the_grant_is_checked_on_every_run(db_session, video, settings, fake, setup, code):
    setup(db_session, db_session.get(User, video.user_id))
    db_session.commit()
    sync = run(db_session, video, settings, fake)
    assert sync.status == "failed" and sync.error_code == code
    assert fake.calls == []  # Google is never asked without the creator's grant
    assert video.next_sync_at is None  # waits for the creator, not retried blindly
    assert days_of(db_session, video) == []


def test_a_refused_grant_marks_the_connection_for_reconnecting(db_session, video, settings, fake):
    fake.fail("authorize", [PerformanceErrorCode.AUTHENTICATION_REQUIRED])
    sync = run(db_session, video, settings, fake)
    assert sync.error_code == "authentication_required"
    assert get_connection(db_session, video.user_id).status == "needs_reconnect"


def test_a_missing_scope_never_marks_publishing_for_reconnecting(db_session, video, settings,
                                                                 fake):  # fmt: skip
    fake.fail("authorize", [PerformanceErrorCode.ANALYTICS_NOT_AUTHORIZED])
    sync = run(db_session, video, settings, fake)
    assert sync.error_code == "analytics_not_authorized"
    assert get_connection(db_session, video.user_id).status == "connected"


def test_the_refresh_token_is_used_but_never_recorded(db_session, video, settings, fake, caplog):
    seen = []
    original = fake.authorize
    fake.authorize = lambda token: seen.append(token) or original(token)
    run(db_session, video, settings, fake)
    assert seen == [REFRESH_TOKEN]
    assert REFRESH_TOKEN not in caplog.text


# --- failures ----------------------------------------------------------------------------------


def test_a_temporary_failure_is_retried_later_with_a_backoff(db_session, video, settings, fake):
    fake.fail("daily_metrics", [PerformanceErrorCode.QUOTA_EXCEEDED] * 2)
    first = run(db_session, video, settings, fake)
    assert first.status == "failed" and first.error_code == "quota_exceeded"
    assert "quota" in first.error_message and "Google" not in first.error_message
    assert video.next_sync_at == NOW + timedelta(hours=1)
    second = run(db_session, video, settings, fake)
    assert second.attempt == 2 and video.next_sync_at == NOW + timedelta(hours=2)
    third = run(db_session, video, settings, fake)
    assert third.status == "completed" and third.attempt == 3
    assert run(db_session, video, settings, fake).attempt == 1  # reset after a success


def test_counters_saved_before_a_failure_are_kept(db_session, video, settings, fake):
    fake.fail("daily_metrics", [PerformanceErrorCode.NETWORK_ERROR])
    assert run(db_session, video, settings, fake).status == "failed"
    assert len(video.snapshots) == 1 and days_of(db_session, video) == []


def test_unexpected_errors_are_recorded_safely(db_session, video, settings, fake, monkeypatch):
    def broken(*args):
        raise RuntimeError("/srv/secret/path exploded")

    monkeypatch.setattr(fake, "daily_metrics", broken)
    sync = run(db_session, video, settings, fake)
    assert sync.error_code == "internal_error" and "/srv" not in sync.error_message


# --- one active sync, fencing ------------------------------------------------------------------


def test_one_active_sync_per_video_and_stalled_ones_are_replaced(db_session, video, settings):
    first = request_sync(db_session, video, "scheduled", settings)
    assert request_sync(db_session, video, "manual", settings) is None
    first.heartbeat_at = first.created_at = syncing.now() - timedelta(hours=1)
    db_session.commit()
    second = request_sync(db_session, video, "manual", settings)
    assert second is not None and second.celery_task_id != first.celery_task_id
    db_session.refresh(first)
    assert first.status == "failed" and first.error_code == "stalled"


def test_a_replaced_worker_never_writes(db_session, video, settings, fake):
    sync = request_sync(db_session, video, "scheduled", settings)
    task = sync.celery_task_id
    assert run_sync(sync.id, db_session, settings=settings, provider=fake, task_id="other",
                    at=NOW).status == "queued"  # fmt: skip
    original = fake.video_counters

    def replaced_meanwhile(auth, ids):
        result = original(auth, ids)
        db_session.execute(text("UPDATE analytics_syncs SET celery_task_id = 'b' WHERE id = :i"),
                           {"i": sync.id})  # fmt: skip
        return result

    fake.video_counters = replaced_meanwhile
    run_sync(sync.id, db_session, settings=settings, provider=fake, task_id=task, at=NOW)
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(PerformanceSnapshot)) == 0
    assert days_of(db_session, video) == []


def test_a_video_deleted_mid_sync_stops_quietly(db_session, video, settings, fake, caplog):
    original, video_id = fake.daily_metrics, video.id

    def deleted_meanwhile(*args):
        db_session.execute(text("DELETE FROM published_contents WHERE id = :i"), {"i": video_id})
        db_session.commit()  # another process deleted the project
        return original(*args)

    fake.daily_metrics = deleted_meanwhile
    run(db_session, video, settings, fake)
    assert "Unexpected error" not in caplog.text
    db_session.expire_all()
    assert db_session.get(PublishedContent, video_id) is None


# --- refreshes and the schedule ----------------------------------------------------------------


def test_a_creator_refresh_has_a_cooldown(db_session, video, settings, fake):
    run(db_session, video, settings, fake)
    with pytest.raises(RefreshTooSoon) as excinfo:
        request_manual_sync(db_session, video, settings, at=NOW + timedelta(minutes=5))
    assert excinfo.value.retry_after_seconds == 600
    assert request_manual_sync(db_session, video, settings, at=NOW + timedelta(minutes=16))


@pytest.mark.parametrize(
    ("age", "gap"),
    [
        (timedelta(hours=3), timedelta(hours=6)),
        (timedelta(days=3), timedelta(hours=12)),
        (timedelta(days=12), timedelta(days=1)),
        (timedelta(days=45), timedelta(days=3)),
        (timedelta(days=120), timedelta(days=7)),
        (timedelta(days=180), None),
    ],
)
def test_the_schedule_slows_down_with_age_and_stops(age, gap):
    expected = NOW + gap if gap else None
    assert next_sync_after(NOW - age, NOW) == expected


@pytest.fixture
def queued(monkeypatch, db_session):
    calls = []

    def enqueue(sync_id, *, task_id):
        assert db_session.get(AnalyticsSync, sync_id).celery_task_id == task_id  # token first
        calls.append(sync_id)
        return task_id

    monkeypatch.setattr(dispatch, "enqueue_performance_sync", enqueue)
    return calls


def test_the_scheduler_starts_only_due_granted_present_idle_videos(db_session, settings, queued):
    user, edit = creator(db_session)
    grant(db_session, user)
    due = make_content(db_session, user, edit, published_at=PUBLISHED, next_sync_at=NOW)
    make_content(db_session, user, edit, published_at=PUBLISHED, next_sync_at=NOW + timedelta(1))
    make_content(db_session, user, edit, published_at=PUBLISHED, next_sync_at=NOW,
                 remote_status="remote_missing")  # fmt: skip
    make_content(db_session, user, edit, published_at=PUBLISHED, next_sync_at=None)
    busy = make_content(db_session, user, edit, published_at=PUBLISHED, next_sync_at=NOW)
    request_sync(db_session, busy, "manual", settings)
    other, other_edit = creator(db_session)
    grant(db_session, other, analytics=False)
    make_content(db_session, other, other_edit, published_at=PUBLISHED, next_sync_at=NOW)
    started = lifecycle.schedule_due(db_session, settings, at=NOW)
    assert started == 1
    assert [db_session.get(AnalyticsSync, s).content_id for s in queued] == [due.id]
    assert lifecycle.schedule_due(db_session, analytics_settings(youtube_analytics_enabled=False),
                                  at=NOW) == 0  # fmt: skip


def test_the_scheduler_is_bounded(db_session, queued):
    user, edit = creator(db_session)
    grant(db_session, user)
    for _ in range(5):
        make_content(db_session, user, edit, published_at=PUBLISHED, next_sync_at=NOW)
    assert lifecycle.schedule_due(db_session, analytics_settings(performance_schedule_batch=3),
                                  at=NOW) == 3  # fmt: skip


def test_a_broker_outage_is_recorded_as_retryable(db_session, video, settings, monkeypatch):
    def down(sync_id, *, task_id):
        raise dispatch.JobQueueUnavailable("down")

    monkeypatch.setattr(dispatch, "enqueue_performance_sync", down)
    sync = lifecycle.start_sync(db_session, video, "manual", settings)
    assert sync.status == "failed" and sync.error_code == "queue_unavailable"
    assert request_sync(db_session, video, "manual", settings) is not None  # not stuck


# --- backfill ----------------------------------------------------------------------------------


def test_a_new_grant_backfills_peaksift_uploads_only(db_session, settings, queued, tmp_path):
    user, _, job = published(db_session, settings, tmp_path)
    content = content_of(db_session, job)
    db_session.delete(content)  # an upload from before V1.4: not linked yet
    db_session.commit()
    grant(db_session, user)
    assert lifecycle.start_backfill(db_session, user.id, settings) == 1
    linked = db_session.scalar(select(PublishedContent).where(PublishedContent.user_id == user.id))
    assert linked.remote_video_id == job.provider_video_id  # only what PeakSift published
    assert [db_session.get(AnalyticsSync, s).kind for s in queued] == ["backfill"]
    assert lifecycle.start_backfill(db_session, user.id, analytics_settings(
        youtube_analytics_enabled=False)) == 0  # fmt: skip


def test_only_the_analytics_callback_starts_a_backfill(client, monkeypatch, google):
    from app.api import publishing as api
    from app.services.publishing import youtube_oauth as oauth
    from tests.test_youtube_oauth import callback, sign_in, start

    configured = analytics_settings()
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    started = []
    monkeypatch.setattr(api, "start_backfill_quietly", lambda db, user_id, s: started.append(1))
    sign_in(client)
    callback(client, state=start(client)["query"]["state"], code="c")
    assert started == []  # publishing never starts analytics
    url = client.post("/publishing/youtube/analytics/connect").json()["authorization_url"]
    google["answer"]["scope"] = [oauth.UPLOAD_SCOPE, oauth.READONLY_SCOPE, oauth.ANALYTICS_SCOPE]
    callback(client, state=parse_qs(urlsplit(url).query)["state"][0], code="c")
    assert started == [1]


def test_operator_commands(monkeypatch, capsys):
    import uuid

    from app.cli import performance as cli

    assert cli.main(["status"]) == 0
    assert "published videos:" in capsys.readouterr().out
    monkeypatch.setattr(cli, "get_settings", lambda: analytics_settings())
    assert cli.main(["backfill", "--user", str(uuid.uuid4())]) == 1
    assert "has not granted analytics access" in capsys.readouterr().err
    monkeypatch.setattr(cli, "get_settings",
                        lambda: analytics_settings(youtube_analytics_enabled=False))  # fmt: skip
    assert cli.main(["sync-due"]) == 0 and "started 0 syncs" in capsys.readouterr().out


def test_the_task_ignores_malformed_ids(caplog):
    from app.workers.performance_tasks import sync_performance_task

    sync_performance_task.run("not-a-uuid")
    assert "invalid id" in caplog.text
