"""The performance analytics domain: linking a published video to the PeakSift output that made
it (on upload, idempotently, never by title), the immutable provenance snapshot, metric
definitions per day, constraints (NULL is not zero, one row per day, one active sync per
content) and deletion semantics."""

import io
import os
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.models import (
    AnalyticsSync,
    PerformanceDailyMetric,
    PerformanceSnapshot,
    PublishedContent,
    PublishJob,
)
from app.services.performance.content import (
    link_existing,
    link_published_content,
)
from app.services.performance.metrics import metric_version
from app.services.performance.provenance import PROVENANCE_VERSION, build_provenance
from app.services.publishing import pipeline
from app.services.publishing.fake import FakePublishingProvider
from app.services.publishing.jobs import request_publish
from app.services.publishing.metadata import PublishMetadata
from app.services.storage import LocalStorageProvider
from tests.publishing_fixtures import KEY, connect, ready_edit

CHUNK = 256 * 1024
V26 = "youtube_views_2026_08"


@pytest.fixture
def settings() -> Settings:
    overrides = {"publishing_token_encryption_key": KEY, "youtube_upload_chunk_bytes": CHUNK}
    return Settings(**{**get_settings().model_dump(), **overrides})


def published(db, settings, tmp_path, title="Our bridge collapsed"):
    """A short really published through the pipeline (fake provider)."""
    storage = LocalStorageProvider(tmp_path / "media")
    user, edit = ready_edit(db)
    storage.save(io.BytesIO(os.urandom(CHUNK + 100)), edit.storage_key)
    connection = connect(db, user)
    job, _ = request_publish(
        db, user_id=user.id, edit=edit, connection=connection, task_id="task-1",
        metadata=PublishMetadata.create(title=title, tags=["peaksift"]),
    )  # fmt: skip
    pipeline.publish_short(
        job.id, db, settings=settings, storage=storage, provider=FakePublishingProvider(),
        task_id="task-1", sleep=lambda s: None, schedule_status_check=None,
    )  # fmt: skip
    db.refresh(job)
    return user, edit, job


def content_of(db, job) -> PublishedContent:
    return db.scalar(select(PublishedContent).where(PublishedContent.publish_job_id == job.id))


# --- linking ---------------------------------------------------------------------------------


def test_an_upload_links_the_remote_video_to_its_peaksift_output(db_session, settings, tmp_path):
    user, edit, job = published(db_session, settings, tmp_path)
    content = content_of(db_session, job)
    assert content is not None and job.provider_video_id
    assert (content.user_id, content.edit_id, content.clip_id) == (user.id, edit.id, edit.clip_id)
    assert content.project_id == edit.clip.video.project_id
    assert content.remote_video_id == job.provider_video_id and content.provider == "youtube"
    assert content.title == "Our bridge collapsed" and content.privacy == "private"
    assert content.remote_status == "active" and content.duration_seconds == 20.0
    assert content.provenance_version == PROVENANCE_VERSION
    assert (
        content.provenance["recipe"] == "manual" and content.provenance["layout"] == "center_crop"
    )
    assert content.auto_edit_plan_id is None


def test_linking_is_idempotent_and_never_by_title(db_session, settings, tmp_path):
    _, _, job = published(db_session, settings, tmp_path)
    first = content_of(db_session, job)
    assert link_published_content(db_session, job).id == first.id
    other = PublishJob(**{c: getattr(job, c) for c in ("user_id", "edit_id", "provider", "title",
                                                         "privacy", "category_id")},
                       fingerprint="f" * 64, provider_video_id=None)  # fmt: skip
    db_session.add(other)
    db_session.flush()
    assert link_published_content(db_session, other) is None  # same title, no video: no link
    count = db_session.scalar(select(func.count()).select_from(PublishedContent))
    assert count >= 1


def test_uploads_from_before_analytics_are_linked_later(db_session, settings, tmp_path):
    user, _, job = published(db_session, settings, tmp_path)
    db_session.delete(content_of(db_session, job))
    db_session.commit()
    assert content_of(db_session, job) is None
    assert link_existing(db_session, user.id) == 1
    assert content_of(db_session, job) is not None
    assert link_existing(db_session, user.id) == 0


def test_a_link_failure_never_fails_the_publish(db_session, settings, tmp_path, monkeypatch):
    def broken(db, job):
        raise RuntimeError("analytics bookkeeping exploded")

    monkeypatch.setattr("app.services.performance.content.link_published_content", broken)
    _, _, job = published(db_session, settings, tmp_path)
    assert job.provider_video_id and job.status in ("uploaded", "processing", "published")
    assert content_of(db_session, job) is None


# --- provenance --------------------------------------------------------------------------------


def _edit(config, **fields):
    defaults = {"duration_seconds": 21.456, "layout": config.get("layout"),
                "captions_enabled": True, "caption_style": None, "caption_position": None,
                "caption_timing": "aligned_word"}  # fmt: skip
    return SimpleNamespace(config=config, **{**defaults, **fields})


FULL = {
    "layout": "smart_reframe",
    "captions": {"enabled": True, "style": "punch", "position": "bottom"},
    "hook": {"text": "Our bridge collapsed", "style": "headline", "position": "top",
             "duration": 2.5},
    "visuals": {"elements": [{"mode": "cutaway", "asset_id": "a"}, {"mode": "pip", "asset_id": "b"},
                             {"mode": "cutaway", "asset_id": "c"}]},
    "audio": {"normalize": True, "music": {"asset_id": "m", "ducking": "medium"},
              "sfx": [{"asset_id": "s", "at_seconds": 1.0}]},
}  # fmt: skip


def test_provenance_is_normalized_features_only():
    plan = SimpleNamespace(
        recipe="punchy", planner_provider="ollama", confidence_summary={"planner": "local_ai"},
        explanation_snapshot={"sections": {"visuals": {"items": [{"matched": "visual"}]}}},
    )  # fmt: skip
    candidate = SimpleNamespace(rank=2, overall_score=81, category="story")
    p = build_provenance(_edit(FULL), plan, candidate)
    assert p["duration_seconds"] == 21.46 and p["recipe"] == "punchy"
    assert p["auto_edit"] == {"used": True, "planner": "local_ai"}
    assert p["layout"] == "smart_reframe"
    assert p["captions"] == {"enabled": True, "preset": "punch", "position": "bottom",
                             "timing": "aligned_word"}  # fmt: skip
    assert p["hook"] == {"enabled": True, "length_chars": 20, "duration_seconds": 2.5,
                         "style": "headline", "position": "top"}  # fmt: skip
    assert p["visuals"] == {"count": 3, "cutaways": 2, "pips": 1, "overlays": 0}
    assert p["audio"] == {"music": True, "ducking": "medium", "sfx_count": 1, "normalized": True}
    assert p["semantic_visuals"] == {"used": True}
    assert p["candidate"] == {"rank": 2, "score": 81, "category": "story"}
    text = str(p)
    assert "Our bridge collapsed" not in text  # lengths, never the words
    assert "asset_id" not in text and "'a'" not in text


def test_manual_edits_without_hook_visuals_or_audio():
    p = build_provenance(_edit({"layout": "blur_background", "captions": {"enabled": False}}),
                         None, None)  # fmt: skip
    assert p["recipe"] == "manual" and p["auto_edit"] == {"used": False, "planner": None}
    assert p["hook"]["enabled"] is False and p["hook"]["length_chars"] == 0
    assert p["visuals"]["count"] == 0
    assert p["audio"] == {"music": False, "ducking": None, "sfx_count": 0, "normalized": False}
    assert p["semantic_visuals"] == {"used": None}  # unknown for manual edits, not "no"
    rules = SimpleNamespace(recipe="minimal", planner_provider="fallback", confidence_summary={},
                            explanation_snapshot={})  # fmt: skip
    p = build_provenance(_edit({"layout": "fit"}), rules, None)
    assert p["auto_edit"]["planner"] == "rules" and p["semantic_visuals"] == {"used": False}


def test_provenance_never_changes_with_later_state(db_session, settings, tmp_path):
    _, edit, job = published(db_session, settings, tmp_path)
    before = dict(content_of(db_session, job).provenance)
    edit.config = {**edit.config, "layout": "fit"}  # something rewriting the past
    edit.layout = "fit"
    db_session.commit()
    db_session.expire_all()
    assert content_of(db_session, job).provenance == before


# --- metric definitions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "version"),
    [
        (date(2025, 3, 30), "youtube_views_legacy"),
        (date(2025, 3, 31), "youtube_views_2025_03"),
        (date(2026, 8, 26), "youtube_views_2025_03"),
        (date(2026, 8, 27), "youtube_views_2026_08"),
        (date(2026, 10, 22), "youtube_views_2026_08"),
    ],
)
def test_each_day_records_the_view_definition_in_force(day, version):
    assert metric_version(day) == version


# --- constraints -------------------------------------------------------------------------------


@pytest.fixture
def content(db_session, settings, tmp_path) -> PublishedContent:
    _, _, job = published(db_session, settings, tmp_path)
    return content_of(db_session, job)


def snapshot(content, **metrics):
    return PerformanceSnapshot(content=content, source="fake", data_class="counters",
                               observed_at=datetime.now(UTC), metric_version=V26,
                               **metrics)  # fmt: skip


def test_null_is_not_zero(db_session, content):
    empty = snapshot(content)  # the provider gave nothing
    zero = snapshot(content, views=0, likes=0)
    db_session.add_all([empty, zero])
    db_session.flush()
    db_session.expire_all()
    assert (empty.views, zero.views) == (None, 0)


@pytest.mark.parametrize("field", ["views", "engaged_views", "likes", "comments",
                                   "watch_time_seconds", "average_view_percentage",
                                   "subscribers_gained"])  # fmt: skip
def test_metrics_are_never_negative(db_session, content, field):
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(snapshot(content, **{field: -1}))
        db_session.flush()


def test_retention_may_exceed_one_hundred_percent(db_session, content):
    db_session.add(snapshot(content, average_view_percentage=134.2))  # replayed Shorts
    db_session.flush()


@pytest.mark.parametrize("changes", [{"source": "tiktok"}, {"data_class": "forecast"}])
def test_snapshot_allow_lists(db_session, content, changes):
    with pytest.raises(IntegrityError), db_session.begin_nested():
        row = snapshot(content)
        for key, value in changes.items():
            setattr(row, key, value)
        db_session.add(row)
        db_session.flush()


def test_one_daily_row_per_content_source_day_and_definition(db_session, content):
    def day(**kw):
        return PerformanceDailyMetric(content=content, source="fake", date=date(2026, 10, 20),
                                      metric_version=V26, views=10, **kw)  # fmt: skip

    db_session.add(day())
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(day())
        db_session.flush()
    db_session.add(PerformanceDailyMetric(content=content, source="youtube",
                                          date=date(2026, 10, 20), metric_version=V26,
                                          views=12))  # fmt: skip
    db_session.flush()  # another source is another row


def test_one_active_sync_per_content(db_session, content):
    db_session.add(AnalyticsSync(content=content, kind="scheduled", celery_task_id="a"))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(AnalyticsSync(content=content, kind="manual", celery_task_id="b"))
        db_session.flush()
    for row in content.syncs:
        row.status, row.completed_at = "completed", datetime.now(UTC)
    db_session.flush()
    db_session.add(AnalyticsSync(content=content, kind="manual", celery_task_id="c"))
    db_session.flush()  # finished syncs never block a new one


def test_a_failed_sync_says_why(db_session, content):
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(AnalyticsSync(content=content, kind="manual", status="failed"))
        db_session.flush()


def test_the_remote_id_is_unique_per_provider(db_session, content):
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(PublishedContent(
            user_id=content.user_id, project_id=content.project_id, provider="youtube",
            remote_video_id=content.remote_video_id, title="x", published_at=datetime.now(UTC),
            provenance={}, provenance_version=PROVENANCE_VERSION,
        ))  # fmt: skip
        db_session.flush()


# --- deletion semantics ---------------------------------------------------------------------


def test_deleting_the_edit_keeps_the_content_and_its_provenance(db_session, content):
    content_id, provenance = content.id, dict(content.provenance)
    db_session.execute(text("DELETE FROM clip_edits WHERE id = :id"), {"id": content.edit_id})
    db_session.expire_all()
    kept = db_session.get(PublishedContent, content_id)
    assert kept is not None and kept.edit_id is None and kept.publish_job_id is None
    assert kept.provenance == provenance


def test_deleting_the_project_deletes_its_analytics(db_session, content):
    db_session.add(snapshot(content, views=3))
    db_session.add(PerformanceDailyMetric(content=content, source="fake", date=date(2026, 10, 20),
                                          metric_version=V26, views=3))  # fmt: skip
    db_session.add(AnalyticsSync(content=content, kind="scheduled", celery_task_id="t"))
    db_session.flush()
    content_id, project_id = content.id, content.project_id
    db_session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
    db_session.expire_all()
    assert db_session.get(PublishedContent, content_id) is None
    for model in (PerformanceSnapshot, PerformanceDailyMetric, AnalyticsSync):
        assert not db_session.scalars(select(model).where(model.content_id == content_id)).all()
