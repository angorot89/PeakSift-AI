import uuid
from datetime import datetime

from pydantic import BaseModel


class ReframeAnalysisRead(BaseModel):
    """A smart-reframing analysis. Never task ids, paths, model files or worker details."""

    id: uuid.UUID
    clip_id: uuid.UUID
    status: str
    progress_percent: int
    attempt: int
    is_stale: bool
    provider: str
    algorithm_version: str
    sample_fps: float
    target_aspect_ratio: str
    source_width: int | None
    source_height: int | None
    overall_confidence: float | None
    confidence_level: str | None
    frames_sampled: int | None
    detections_count: int | None
    tracks_count: int | None
    subject_switches: int | None
    fallback_fraction: float | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ReframeAnalysisPage(BaseModel):
    total: int
    analyses: list[ReframeAnalysisRead]


class CropKeyframeRead(BaseModel):
    """One crop-path point: clip-local seconds and fractions of the display-oriented source."""

    timestamp: float
    center_x: float
    center_y: float
    crop_width: float
    crop_height: float
    confidence: float
    mode: str


class CropPathRead(BaseModel):
    """The completed crop path, in order. Interpolate linearly between keyframes."""

    analysis_id: uuid.UUID
    source_width: int
    source_height: int
    target_aspect_ratio: str
    keyframes: list[CropKeyframeRead]
