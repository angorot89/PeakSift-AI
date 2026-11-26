"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.audio_asset import AudioAsset, AudioAssetKind
from app.models.auto_edit import (
    ACTIVE_AUTO_EDIT_STATUSES,
    FINISHED_AUTO_EDIT_STATUSES,
    AutoEditPlan,
    AutoEditRecipe,
    AutoEditStatus,
)
from app.models.brand import BrandProfile
from app.models.broll import (
    ACTIVE_BROLL_ANALYSIS_STATUSES,
    BrollAnalysis,
    BrollAnalysisStatus,
    BrollSuggestion,
    BrollSuggestionStatus,
)
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
    CandidateOrigin,
    ClipCandidate,
    ClipDetectionRun,
    ClipDetectionStatus,
)
from app.models.clip_edit import ACTIVE_CLIP_EDIT_STATUSES, ClipEdit, ClipEditStatus
from app.models.copilot import CopilotMessage, CopilotMessageStatus, CopilotRole, CopilotThread
from app.models.insight import CreatorInsight, InsightConfidence, InsightSet, InsightSetStatus
from app.models.oauth_state import OAuthState
from app.models.performance import (
    ACTIVE_SYNC_STATUSES,
    AnalyticsSync,
    DataSource,
    PerformanceDailyMetric,
    PerformanceSnapshot,
    PublishedContent,
    RemoteStatus,
    SnapshotClass,
    SyncKind,
    SyncStatus,
)
from app.models.project import Project, ProjectStatus
from app.models.publish_job import (
    ACTIVE_PUBLISH_STATUSES,
    FINISHED_UPLOAD_STATUSES,
    Privacy,
    PublishJob,
    PublishStatus,
)
from app.models.publishing_connection import (
    ConnectionStatus,
    PublishingConnection,
    PublishingProvider,
)
from app.models.reframe import (
    ACTIVE_REFRAME_STATUSES,
    KeyframeMode,
    ReframeAnalysis,
    ReframeConfidence,
    ReframeKeyframe,
    ReframeStatus,
)
from app.models.semantic import (
    ACTIVE_SEMANTIC_INDEX_STATUSES,
    EMBEDDING_DIMENSIONS,
    AssetEmbedding,
    SemanticIndexStatus,
    VisualSemanticIndex,
)
from app.models.short_template import ShortTemplate
from app.models.transcription import (
    ACTIVE_TRANSCRIPTION_STATUSES,
    Transcription,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.models.user import User
from app.models.video import Video, VideoStatus
from app.models.visual_asset import VisualAsset, VisualAssetKind

__all__ = [
    "ShortTemplate",
    "BrandProfile",
    "CopilotMessage",
    "CopilotMessageStatus",
    "CopilotRole",
    "CopilotThread",
    "CreatorInsight",
    "InsightConfidence",
    "InsightSet",
    "InsightSetStatus",
    "ACTIVE_AUTO_EDIT_STATUSES",
    "FINISHED_AUTO_EDIT_STATUSES",
    "AutoEditPlan",
    "AutoEditRecipe",
    "AutoEditStatus",
    "ACTIVE_BROLL_ANALYSIS_STATUSES",
    "BrollAnalysis",
    "BrollAnalysisStatus",
    "BrollSuggestion",
    "BrollSuggestionStatus",
    "ACTIVE_PUBLISH_STATUSES",
    "FINISHED_UPLOAD_STATUSES",
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
    "CandidateOrigin",
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
    "ConnectionStatus",
    "OAuthState",
    "Privacy",
    "PublishJob",
    "PublishStatus",
    "Project",
    "ACTIVE_SYNC_STATUSES",
    "AnalyticsSync",
    "DataSource",
    "PerformanceDailyMetric",
    "PerformanceSnapshot",
    "PublishedContent",
    "RemoteStatus",
    "SnapshotClass",
    "SyncKind",
    "SyncStatus",
    "ProjectStatus",
    "PublishingConnection",
    "PublishingProvider",
    "ReframeAnalysis",
    "ReframeConfidence",
    "ReframeKeyframe",
    "ReframeStatus",
    "ACTIVE_SEMANTIC_INDEX_STATUSES",
    "EMBEDDING_DIMENSIONS",
    "AssetEmbedding",
    "SemanticIndexStatus",
    "VisualSemanticIndex",
    "Transcription",
    "TranscriptionStatus",
    "TranscriptSegment",
    "User",
    "Video",
    "VideoStatus",
    "VisualAsset",
    "VisualAssetKind",
]
