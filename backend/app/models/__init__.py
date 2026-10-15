"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.audio_asset import AudioAsset, AudioAssetKind
from app.models.caption_track import (
    ACTIVE_CAPTION_TRACK_STATUSES,
    CaptionTrack,
    CaptionTrackStatus,
    CaptionWord,
)
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
from app.models.clip_edit import ACTIVE_CLIP_EDIT_STATUSES, ClipEdit, ClipEditStatus
from app.models.project import Project, ProjectStatus
from app.models.reframe import (
    ACTIVE_REFRAME_STATUSES,
    KeyframeMode,
    ReframeAnalysis,
    ReframeConfidence,
    ReframeKeyframe,
    ReframeStatus,
)
from app.models.transcription import (
    ACTIVE_TRANSCRIPTION_STATUSES,
    Transcription,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.models.user import User
from app.models.video import Video, VideoStatus

__all__ = [
    "AudioAsset",
    "AudioAssetKind",
    "ACTIVE_CAPTION_TRACK_STATUSES",
    "ACTIVE_CLIP_DETECTION_STATUSES",
    "ACTIVE_CLIP_EDIT_STATUSES",
    "ACTIVE_CLIP_STATUSES",
    "ACTIVE_REFRAME_STATUSES",
    "ACTIVE_TRANSCRIPTION_STATUSES",
    "CANDIDATE_CATEGORIES",
    "CLIP_CONTENT_TYPE",
    "RENDER_PROFILE_SOURCE_MP4_V1",
    "CandidateDecision",
    "CaptionTrack",
    "CaptionTrackStatus",
    "CaptionWord",
    "Clip",
    "ClipCandidate",
    "ClipDetectionRun",
    "ClipDetectionStatus",
    "ClipEdit",
    "ClipEditStatus",
    "ClipStatus",
    "KeyframeMode",
    "Project",
    "ProjectStatus",
    "ReframeAnalysis",
    "ReframeConfidence",
    "ReframeKeyframe",
    "ReframeStatus",
    "Transcription",
    "TranscriptionStatus",
    "TranscriptSegment",
    "User",
    "Video",
    "VideoStatus",
]
