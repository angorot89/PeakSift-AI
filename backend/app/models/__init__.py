"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.clip import (
    ACTIVE_CLIP_STATUSES,
    CLIP_CONTENT_TYPE,
    RENDER_PROFILE_SOURCE_MP4_V1,
    Clip,
    ClipStatus,
)
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
    "ACTIVE_CLIP_STATUSES",
    "ACTIVE_TRANSCRIPTION_STATUSES",
    "CANDIDATE_CATEGORIES",
    "CLIP_CONTENT_TYPE",
    "RENDER_PROFILE_SOURCE_MP4_V1",
    "CandidateDecision",
    "Clip",
    "ClipCandidate",
    "ClipDetectionRun",
    "ClipDetectionStatus",
    "ClipStatus",
    "Project",
    "ProjectStatus",
    "Transcription",
    "TranscriptionStatus",
    "TranscriptSegment",
    "User",
    "Video",
    "VideoStatus",
]
