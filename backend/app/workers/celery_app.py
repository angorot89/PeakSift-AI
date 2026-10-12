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

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "peaksift",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.transcription_tasks"],
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
