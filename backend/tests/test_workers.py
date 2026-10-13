import os
import time
import uuid

import pytest
from kombu.exceptions import OperationalError

from app.core.config import get_settings
from app.workers import dispatch
from app.workers.celery_app import celery_app
from app.workers.dispatch import JobQueueUnavailable, enqueue_transcription
from app.workers.transcription_tasks import ping, transcribe_video


def _redis_reachable() -> bool:
    try:
        import redis

        redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_reachable() and not os.environ.get("REQUIRE_REDIS"), reason="Redis not reachable"
)


# --- configuration -----


def test_celery_uses_redis_and_json_only():
    conf = celery_app.conf
    assert conf.broker_url == get_settings().redis_url
    assert conf.task_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.task_ignore_result is True


def test_long_task_semantics():
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_soft_time_limit == get_settings().celery_task_soft_time_limit_seconds
    assert conf.task_time_limit == get_settings().celery_task_time_limit_seconds
    assert conf.task_time_limit > conf.task_soft_time_limit
    # Redis must not redeliver an unacknowledged job before it can legitimately finish.
    assert conf.broker_transport_options["visibility_timeout"] > conf.task_time_limit


def test_tests_run_tasks_eagerly():
    assert celery_app.conf.task_always_eager is True
    assert celery_app.conf.task_eager_propagates is True


def test_tasks_are_registered():
    assert "peaksift.ping" in celery_app.tasks
    assert "peaksift.transcribe_video" in celery_app.tasks
    assert celery_app.tasks["peaksift.transcribe_video"].name == transcribe_video.name


# --- eager execution -----


def test_ping_runs_inline_in_eager_mode():
    assert ping.delay().get() == "pong"


def test_transcribe_video_for_unknown_id_is_a_quiet_noop(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.workers.transcription_tasks.SessionLocal", lambda: _Reusable(db_session)
    )

    transcribe_video.delay(str(uuid.uuid4()))  # must not raise


class _Reusable:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


def test_worker_processes_reset_the_database_pool():
    from celery.signals import worker_process_init

    from app.workers import celery_app as module

    receivers = [r for r in worker_process_init.receivers]
    assert receivers, "worker_process_init handler must be registered"
    assert hasattr(module, "_reset_database_pool")


def test_enqueue_returns_task_id_and_passes_only_the_id(monkeypatch):
    seen: dict = {}

    def fake_apply_async(*, args, task_id, retry):
        seen.update(args=args, task_id=task_id, retry=retry)

    monkeypatch.setattr(dispatch.transcribe_video, "apply_async", fake_apply_async)
    transcription_id = uuid.uuid4()

    assert enqueue_transcription(transcription_id, task_id="task-123") == "task-123"
    assert seen == {"args": [str(transcription_id)], "task_id": "task-123", "retry": False}


# --- broker unavailable -----


def test_enqueue_when_broker_is_down_is_a_controlled_error(monkeypatch):
    def failing_apply_async(**kwargs):
        raise OperationalError("Error 61 connecting to localhost:6379. Connection refused.")

    monkeypatch.setattr(dispatch.transcribe_video, "apply_async", failing_apply_async)

    with pytest.raises(JobQueueUnavailable):
        enqueue_transcription(uuid.uuid4(), task_id="task-x")


def test_real_broker_outage_fails_fast():
    """apply_async(retry=False) against an unreachable Redis raises OperationalError quickly,
    which is exactly what dispatch translates into JobQueueUnavailable."""
    from celery import Celery

    probe = Celery("outage-probe", broker="redis://127.0.0.1:1/0")
    probe.conf.update(broker_connection_timeout=1, broker_connection_retry=False)

    @probe.task(name="probe.noop")
    def noop() -> None:
        return None

    started = time.monotonic()
    with pytest.raises(OperationalError):
        noop.apply_async(retry=False)
    assert time.monotonic() - started < 10


# --- live Redis (skipped when unavailable, required in CI) -------------------------------


@requires_redis
def test_broker_connection_to_live_redis():
    with celery_app.connection_for_write() as connection:
        connection.ensure_connection(max_retries=1)
        assert connection.connected
