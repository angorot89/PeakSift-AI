"""Enqueue background jobs with controlled failure when the broker is unavailable."""

import uuid

from kombu.exceptions import OperationalError

from app.workers.broll_tasks import suggest_broll_task
from app.workers.caption_tasks import generate_caption_track_task
from app.workers.clip_detection_tasks import detect_clips
from app.workers.clip_edit_tasks import render_clip_edit_task
from app.workers.clip_render_tasks import render_clip_task
from app.workers.publish_tasks import publish_short_task
from app.workers.reframe_tasks import analyze_reframe_task
from app.workers.transcription_tasks import transcribe_video


class JobQueueUnavailable(Exception):
    """Redis could not be reached; the caller should surface a temporary failure."""


def enqueue_transcription(transcription_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `transcribe_video` under a pre-chosen task id (already committed on the row as
    its fencing token) and return it.

    `retry=False` makes a broker outage fail fast instead of blocking the request while
    kombu retries; the API turns this into a 503.
    """
    try:
        transcribe_video.apply_async(args=[str(transcription_id)], task_id=task_id, retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id


def new_task_id() -> str:
    """A task id chosen *before* the job row is committed, so the fencing token is on the
    row before any worker can see the job. Every background job uses this."""
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


def enqueue_clip_edit(edit_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `render_clip_edit` under a pre-chosen task id and return it."""
    try:
        render_clip_edit_task.apply_async(args=[str(edit_id)], task_id=task_id, retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id


def enqueue_caption_track(caption_track_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `generate_caption_track` under a pre-chosen task id and return it."""
    try:
        generate_caption_track_task.apply_async(
            args=[str(caption_track_id)], task_id=task_id, retry=False
        )
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id


def enqueue_broll_analysis(analysis_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `suggest_broll` under a pre-chosen task id and return it."""
    try:
        suggest_broll_task.apply_async(args=[str(analysis_id)], task_id=task_id, retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id


def enqueue_reframe_analysis(analysis_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `analyze_reframe` under a pre-chosen task id and return it."""
    try:
        analyze_reframe_task.apply_async(args=[str(analysis_id)], task_id=task_id, retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id


def enqueue_publish(publish_job_id: uuid.UUID, *, task_id: str) -> str:
    """Queue `publish_short` under a pre-chosen task id (the job's fencing token)."""
    try:
        publish_short_task.apply_async(args=[str(publish_job_id)], task_id=task_id, retry=False)
    except OperationalError as error:
        raise JobQueueUnavailable("The job queue is unavailable") from error
    return task_id
