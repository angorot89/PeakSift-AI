"""Enqueue background jobs with controlled failure when the broker is unavailable."""

import uuid

from kombu.exceptions import OperationalError

from app.workers.clip_detection_tasks import detect_clips
from app.workers.clip_render_tasks import render_clip_task
from app.workers.transcription_tasks import transcribe_video


class JobQueueUnavailable(Exception):
    """Redis could not be reached; the caller should surface a temporary failure."""


def enqueue_transcription(transcription_id: uuid.UUID) -> str:
    """Queue `transcribe_video` and return the Celery task id.

    `retry=False` makes a broker outage fail fast instead of blocking the request while
    kombu retries; the API turns this into a 503.
    """
    try:
        result = transcribe_video.apply_async(args=[str(transcription_id)], retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return result.id


def new_task_id() -> str:
    """A task id chosen *before* the job row is committed, so the fencing token is on the
    row before any worker can see the job (the V0.3 transcription flow stored it after)."""
    return str(uuid.uuid4())


def enqueue_clip_detection(run_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `detect_clips` under a pre-chosen task id and return it."""
    try:
        detect_clips.apply_async(args=[str(run_id)], task_id=task_id, retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id


def enqueue_clip_render(clip_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `render_clip` under a pre-chosen task id and return it."""
    try:
        render_clip_task.apply_async(args=[str(clip_id)], task_id=task_id, retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id
