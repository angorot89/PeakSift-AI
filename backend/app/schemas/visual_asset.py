"""Visual asset responses. Never storage keys, file paths, hashes or probe internals."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VisualAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    display_name: str
    content_type: str
    file_size: int
    width: int  # display size (after rotation / sample aspect ratio)
    height: int
    duration_seconds: float | None
    fps: float | None
    has_alpha: bool
    has_audio: bool
    has_thumbnail: bool
    created_at: datetime


class VisualUploadLimits(BaseModel):
    max_bytes: int
    max_video_duration_seconds: float
    max_image_pixels: int
    max_video_pixels: int
    accepted_extensions: list[str]
