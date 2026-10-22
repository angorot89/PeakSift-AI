# ruff: noqa: F811 - the bucket fixture imported from test_s3_media_regression is a parameter here
"""V1.4 performance analytics on the CI matrix: publish → link → grant → sync on object storage
(moto, and the live MinIO CI requires) with nothing written to local media; and the CI workflow
keeps every performance suite, the insights benchmark gate, the simulated provider, no Google
credentials, and the beat process in the production stack."""

import io
import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.models import PerformanceDailyMetric, PublishedContent
from app.services.performance.fake import FakeMetricsProvider
from app.services.performance.metrics import reporting_today
from app.services.performance.sync import request_sync, run_sync
from app.services.publishing import pipeline
from app.services.publishing.fake import FakePublishingProvider
from app.services.publishing.jobs import request_publish
from app.services.publishing.metadata import PublishMetadata
from tests.performance_fixtures import analytics_settings, grant
from tests.publishing_fixtures import KEY, connect, ready_edit
from tests.test_s3_media_regression import bucket, files_under  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
CHUNK = 256 * 1024


def test_the_ci_workflow_runs_every_performance_suite_and_gate():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert 'PERFORMANCE_PROVIDER: "fake"' in ci  # simulated metrics only
    assert "python scripts/insights_benchmark.py" in ci  # the false-pattern gate
    for credential in ("GOOGLE_CLIENT_SECRET", "GOOGLE_CLIENT_ID:", "YOUTUBE_ANALYTICS_ENABLED"):
        assert credential not in ci  # CI never has Google credentials or calls Google
    suites = sorted(
        p.name for p in TESTS.glob("test_*.py")
        if p.name.startswith("test_performance_") or p.name in {
            "test_analytics_permission.py", "test_creator_insights.py",
            "test_auto_edit_performance_context.py"}
    )  # fmt: skip
    missing = [name for name in suites if f"tests/{name}" not in ci]
    assert not missing, f"performance suites not listed in CI: {missing}"
    assert "for service in api worker beat frontend" in ci  # beat runs unprivileged too
    smoke = (ROOT / "backend/scripts/celery_smoke.py").read_text()
    assert (
        '"peaksift.sync_performance"' in smoke and '"peaksift.schedule_performance_syncs"' in smoke
    )
    compose = (ROOT / "deploy/docker-compose.prod.yml").read_text()
    assert '"celery", "-A", "app.workers.celery_app", "beat"' in compose
    assert "YOUTUBE_ANALYTICS_ENABLED: ${YOUTUBE_ANALYTICS_ENABLED:-false}" in compose


def test_publish_link_and_sync_on_object_storage(db_session, bucket):  # noqa: F811
    local_before = set(files_under(Path(get_settings().media_root)))
    user, edit = ready_edit(db_session)
    bucket.save(io.BytesIO(os.urandom(CHUNK + 100)), edit.storage_key)
    publishing = Settings(**{**get_settings().model_dump(), "publishing_token_encryption_key": KEY,
                             "youtube_upload_chunk_bytes": CHUNK})  # fmt: skip
    job, _ = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connect(db_session, user),
        task_id="task-1", metadata=PublishMetadata.create(title="On the bucket", tags=[]),
    )  # fmt: skip
    pipeline.publish_short(
        job.id, db_session, settings=publishing, storage=bucket,
        provider=FakePublishingProvider(), task_id="task-1", sleep=lambda s: None,
        schedule_status_check=None,
    )  # fmt: skip
    content = db_session.scalar(
        select(PublishedContent).where(PublishedContent.publish_job_id == job.id)
    )
    assert content is not None and content.provenance["layout"] == "center_crop"

    grant(db_session, user)  # the creator's explicit analytics upgrade
    settings = analytics_settings()
    at = content.published_at + timedelta(days=9)
    fake = FakeMetricsProvider(today=lambda: reporting_today(at))
    fake.register(content.remote_video_id, reporting_today(content.published_at))
    sync = request_sync(db_session, content, "backfill", settings)
    run_sync(sync.id, db_session, settings=settings, provider=fake, task_id=sync.celery_task_id,
             at=at)  # fmt: skip
    assert sync.status == "completed" and sync.days_upserted >= 7
    days = db_session.scalar(select(func.count()).select_from(PerformanceDailyMetric)
                             .where(PerformanceDailyMetric.content_id == content.id))  # fmt: skip
    assert days == sync.days_upserted
    assert set(files_under(Path(get_settings().media_root))) == local_before  # nothing local


def test_the_insights_benchmark_runs_and_its_gates_pass():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "backend/scripts/insights_benchmark.py"), "--libraries", "40"],
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout[-500:]
    assert "safety gates: PASS" in result.stdout
    assert "outside the observational templates: 0" in result.stdout
