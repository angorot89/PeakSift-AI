"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.clip_detection import (
    ACTIVE_CLIP_DETECTION_STATUSES,
    CANDIDATE_CATEGORIES,
    CandidateDecision,
    ClipCandidate,
    ClipDetectionRun,
    ClipDetectionStatus,
)
from app.models.project import Project, ProjectStatus
from app.models.transcription import (
    ACTIVE_TRANSCRIPTION_STATUSES,
    Transcription,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.models.user import User
from app.models.video import Video, VideoStatus

__all__ = [
    "ACTIVE_CLIP_DETECTION_STATUSES",
    "ACTIVE_TRANSCRIPTION_STATUSES",
    "CANDIDATE_CATEGORIES",
    "CandidateDecision",
    "ClipCandidate",
    "ClipDetectionRun",
    "ClipDetectionStatus",
    "Project",
    "ProjectStatus",
    "Transcription",
    "TranscriptionStatus",
    "TranscriptSegment",
    "User",
    "Video",
    "VideoStatus",
]
