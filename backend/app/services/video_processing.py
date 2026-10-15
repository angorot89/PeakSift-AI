"""Post-upload processing: read metadata and move the video to ready or failed."""

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Video, VideoStatus
from app.services.ffprobe import ProbeError, probe
from app.services.storage import LocalStorageProvider

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500


def process_video_metadata(db: Session, storage: LocalStorageProvider, video: Video) -> Video:
    """uploaded → processing_metadata → ready, or → failed with a safe error message.

    Runs synchronously for Milestone 2. Never raises for a bad file: a broken upload
    becomes a `failed` record rather than a failed request.
    """
    settings = get_settings()
    video.status = VideoStatus.PROCESSING_METADATA
    video.error_message = None
    db.commit()

    try:
        metadata = probe(
            storage.path_for(video.storage_key),
            ffprobe_path=settings.ffprobe_path,
            timeout_seconds=settings.ffprobe_timeout_seconds,
        )
    except ProbeError as error:
        return _mark_failed(db, video, str(error))
    except Exception:
        logger.exception("Unexpected error while probing video %s", video.id)
        return _mark_failed(db, video, "Unexpected error while reading the video")

    video.duration_seconds = metadata.duration_seconds
    video.width = metadata.width
    video.height = metadata.height
    video.fps = metadata.fps
    video.video_codec = metadata.video_codec
    video.audio_codec = metadata.audio_codec
    video.status = VideoStatus.READY
    db.commit()
    return video


def _mark_failed(db: Session, video: Video, message: str) -> Video:
    video.status = VideoStatus.FAILED
    video.error_message = message[:MAX_ERROR_LENGTH]
    db.commit()
    return video
