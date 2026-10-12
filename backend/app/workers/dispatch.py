"""Enqueue background jobs with controlled failure when the broker is unavailable."""

import uuid

from kombu.exceptions import OperationalError

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
