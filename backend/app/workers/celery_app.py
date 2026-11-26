"""Celery application.

Run a worker from ``backend/`` with::

    celery -A app.workers.celery_app worker --loglevel=info

Semantics chosen for long transcription jobs:

- ``task_ignore_result``: the database is the source of truth for job state; Celery's
  result backend is never consulted for user-visible status. (The ``ping`` task opts in
  to a result so a real worker can be smoke-tested.)
- ``task_acks_late`` + ``worker_prefetch_multiplier = 1``: a worker takes one job at a
  time and only acknowledges it when done, so a crash re-queues the job instead of
  losing it. Tasks must therefore be idempotent, which the pipeline guarantees through
  database state (a completed transcription is never redone; an in-flight one is not
  started twice).
- Redis ``visibility_timeout`` is kept above the hard time limit; otherwise Redis would
  hand an unacknowledged long job to a second worker while the first is still working.
- Soft/hard time limits are generous because a multi-hour stream on CPU can take hours.
"""

from celery import Celery
from celery.signals import (
    before_task_publish,
    setup_logging,
    task_postrun,
    task_prerun,
    worker_process_init,
)

from app.core.config import get_settings
from app.core.observability import configure_logging, job_var, request_id_var

settings = get_settings()

celery_app = Celery(
    "peaksift",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.transcription_tasks",
        "app.workers.clip_detection_tasks",
        "app.workers.clip_render_tasks",
        "app.workers.clip_edit_tasks",
        "app.workers.reframe_tasks",
        "app.workers.caption_tasks",
        "app.workers.broll_tasks",
        "app.workers.auto_edit_tasks",
        "app.workers.semantic_tasks",
        "app.workers.publish_tasks",
        "app.workers.performance_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    broker_transport_options={
        "visibility_timeout": settings.celery_task_time_limit_seconds + 3600,
    },
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
)
# Celery beat (one `celery -A app.workers.celery_app beat` process per deployment) runs the
# analytics scheduler (the task does nothing unless analytics is enabled) and releases
# scheduled posts.
celery_app.conf.beat_schedule = {
    "schedule-performance-syncs": {
        "task": "peaksift.schedule_performance_syncs",
        "schedule": float(settings.performance_schedule_interval_seconds),
    },
    # Scheduled publishing: release the posts whose time has come.
    "release-scheduled-publishes": {
        "task": "peaksift.release_scheduled_publishes",
        "schedule": float(settings.publish_schedule_interval_seconds),
    },
}
if settings.semantic_queue:
    # Model inference can get its own workers; everything else stays on the default queue.
    celery_app.conf.task_routes = {
        "peaksift.index_visual_asset": {"queue": settings.semantic_queue},
    }


@worker_process_init.connect
def _reset_database_pool(**_: object) -> None:
    """Forked worker processes must not share the parent's PostgreSQL connections."""
    from app.core.database import engine

    engine.dispose(close=False)


# --- logging and correlation ---------------------------------------------------------------

REQUEST_ID_HEADER = "peaksift_request_id"
_job_tokens: dict[str, tuple] = {}


@setup_logging.connect
def _configure_logging(**_: object) -> None:
    """Workers log through the same redacting handler (JSON in production) as the API."""
    configure_logging(get_settings())


@before_task_publish.connect
def _carry_request_id(headers: dict | None = None, **_: object) -> None:
    """A job enqueued while handling a request carries that request's id to the worker."""
    if headers is not None and (request_id := request_id_var.get()):
        headers[REQUEST_ID_HEADER] = request_id


@task_prerun.connect
def _enter_job(task_id: str | None = None, task=None, args=None, **_: object) -> None:
    job = {"task": task.name, "job_id": str(args[0]) if args else None}
    tokens = (job_var.set(job),)
    if request_id := task.request.get(REQUEST_ID_HEADER):  # absent in eager mode: inherit
        tokens += (request_id_var.set(request_id),)
    _job_tokens[task_id] = tokens


@task_postrun.connect
def _leave_job(task_id: str | None = None, **_: object) -> None:
    for token in reversed(_job_tokens.pop(task_id, ())):
        token.var.reset(token)
