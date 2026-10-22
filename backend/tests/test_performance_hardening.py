"""Performance analytics hardening: a stalled sync never blocks the schedule, a reused remote id
never borrows another job's row, creators can delete what was collected, and logs carry no
tokens, titles or credentials."""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.api import performance as api
from app.models import (
    AnalyticsSync,
    InsightSet,
    PerformanceDailyMetric,
    PerformanceSnapshot,
    PublishedContent,
    PublishJob,
)
from app.services.performance import lifecycle
from app.services.performance import sync as syncing
from app.services.performance.content import link_existing, link_published_content
from app.services.performance.fake import FakeMetricsProvider
from app.services.performance.metrics import reporting_today
from app.services.performance.sync import request_sync, run_sync
from app.workers import dispatch
from tests.performance_fixtures import (
    NOW,
    analytics_settings,
    creator,
    grant,
    make_content,
    provenance,
    signed_in_creator,
    with_week,
)
from tests.publishing_fixtures import REFRESH_TOKEN
from tests.test_performance_domain import content_of, published

PUBLISHED = NOW - timedelta(days=12)


@pytest.fixture
def settings(monkeypatch):
    configured = analytics_settings()
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


def test_a_stalled_sync_never_blocks_the_schedule(db_session, settings, monkeypatch):
    queued = []
    monkeypatch.setattr(dispatch, "enqueue_performance_sync",
                        lambda sync_id, *, task_id: queued.append(sync_id) or task_id)  # fmt: skip
    at = syncing.now()  # the stall check uses the real clock
    user, edit = creator(db_session)
    grant(db_session, user)
    content = make_content(db_session, user, edit, published_at=at - timedelta(days=12),
                           next_sync_at=at)  # fmt: skip
    dead = request_sync(db_session, content, "scheduled", settings)
    dead.status = "syncing"
    dead.started_at = dead.heartbeat_at = dead.created_at = at - timedelta(hours=2)
    db_session.commit()
    assert lifecycle.schedule_due(db_session, settings, at=at) == 1
    db_session.refresh(dead)
    assert dead.status == "failed" and dead.error_code == "stalled"
    content.next_sync_at = at  # due again, but its new sync is live: it still blocks
    db_session.commit()
    assert lifecycle.schedule_due(db_session, settings, at=at) == 0


def test_a_reused_simulated_id_never_borrows_another_jobs_row(db_session, tmp_path):
    settings = analytics_settings(youtube_upload_chunk_bytes=256 * 1024)
    first_user, _, first_job = published(db_session, settings, tmp_path / "a")
    owner = content_of(db_session, first_job)
    db_session.delete(first_job)  # the content stays (its job link becomes empty)
    db_session.commit()
    # A fresh simulated provider hands out the same id again ("fake-000001").
    second_user, _, second_job = published(db_session, settings, tmp_path / "b")
    assert second_job.provider_video_id == owner.remote_video_id
    assert content_of(db_session, second_job) is None
    assert link_published_content(db_session, second_job) is None
    assert link_existing(db_session, second_user.id) == 0
    db_session.refresh(owner)
    assert owner.user_id == first_user.id and owner.publish_job_id is None


def test_a_creator_can_delete_everything_collected(client, db_session, settings):
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    for n in range(12):
        content = make_content(db_session, user, edit, published_at=PUBLISHED - timedelta(n),
                               provenance=provenance(hook=n < 6))  # fmt: skip
        with_week(db_session, content, 200 if n < 6 else 100)
    request_sync(db_session, content, "manual", settings)
    assert client.get("/performance/insights").json()["insights"]
    other, other_edit = creator(db_session)
    kept = with_week(db_session, make_content(db_session, other, other_edit,
                                              published_at=PUBLISHED), 50)  # fmt: skip

    response = client.delete("/performance/data")
    assert response.status_code == 200
    assert response.json() == {"snapshots": 12, "days": 84, "syncs": 1, "insight_sets": 1}
    mine = select(PublishedContent.id).where(PublishedContent.user_id == user.id)
    for model in (PerformanceSnapshot, PerformanceDailyMetric, AnalyticsSync):
        assert db_session.scalar(select(func.count()).select_from(model)
                                 .where(model.content_id.in_(mine))) == 0  # fmt: skip
    assert db_session.scalar(select(func.count()).select_from(InsightSet)
                             .where(InsightSet.user_id == user.id)) == 0  # fmt: skip
    videos = client.get("/performance").json()["videos"]
    assert len(videos) == 12 and all(v["views"] is None and v["next_sync_at"] is None
                                     for v in videos)  # fmt: skip
    assert len(kept.daily_metrics) == 7  # nobody else's data is touched
    client.cookies.clear()
    assert client.delete("/performance/data").status_code == 401


def test_logs_carry_no_tokens_titles_or_credentials(client, db_session, settings, caplog):
    caplog.set_level(logging.DEBUG)
    user, edit = signed_in_creator(db_session, client)
    grant(db_session, user)
    content = make_content(db_session, user, edit, published_at=PUBLISHED,
                           title="My secret launch video")  # fmt: skip
    fake = FakeMetricsProvider(today=lambda: reporting_today(NOW))
    fake.register(content.remote_video_id, reporting_today(PUBLISHED))
    sync = request_sync(db_session, content, "scheduled", settings)
    run_sync(sync.id, db_session, settings=settings, provider=fake, task_id=sync.celery_task_id,
             at=NOW)  # fmt: skip
    fake.fail("daily_metrics", ["authentication_required"])
    sync = request_sync(db_session, content, "manual", settings)
    run_sync(sync.id, db_session, settings=settings, provider=fake, task_id=sync.celery_task_id,
             at=NOW + timedelta(hours=1))  # fmt: skip
    client.get("/performance")
    client.get(f"/performance/videos/{content.id}")
    client.get("/performance/insights")
    text = caplog.text
    for secret in (REFRESH_TOKEN, "fake-metrics-", "Bearer", "My secret launch video",
                   settings.publishing_token_encryption_key.get_secret_value()):  # fmt: skip
        assert secret not in text


def test_old_publish_jobs_without_a_video_are_never_linked(db_session, tmp_path):
    settings = analytics_settings(youtube_upload_chunk_bytes=256 * 1024)
    user, _, job = published(db_session, settings, tmp_path)
    failed = PublishJob(
        user_id=user.id, edit_id=job.edit_id, provider="youtube", title="x", privacy="private",
        category_id=job.category_id, fingerprint="e" * 64,
    )  # fmt: skip
    db_session.add(failed)
    db_session.commit()
    assert link_published_content(db_session, failed) is None
    assert link_existing(db_session, user.id) == 0
