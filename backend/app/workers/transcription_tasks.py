"""Transcription tasks. Only database ids travel through the broker — never model
objects, file handles, media bytes or secrets."""

from app.workers.celery_app import celery_app


@celery_app.task(name="peaksift.ping", ignore_result=False)
def ping() -> str:
    """Round-trip check used to verify a real broker + worker setup."""
    return "pong"


@celery_app.task(name="peaksift.transcribe_video")
def transcribe_video(transcription_id: str) -> None:
    """Run the transcription pipeline for a `Transcription` row (implemented in a later PR)."""
    raise NotImplementedError("The transcription pipeline is not implemented yet")
