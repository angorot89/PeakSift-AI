"""Visual asset responses. Never storage keys, file paths, hashes or probe internals."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.services.visual_assets import (
    DESCRIPTION_MAX_LENGTH,
    TAG_MAX_LENGTH,
    TAGS_MAX,
)


class VisualSearchRead(BaseModel):
    """Whether the asset can be found by what it shows. Never a model name, path or trace."""

    # unavailable / not_indexed / queued / indexing / ready / failed / stale
    state: str
    frames_done: int | None = None  # videos while indexing: real progress
    frames_total: int | None = None
    message: str | None = None  # failed only: a safe, creator-facing reason
    can_retry: bool = False


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
    description: str
    tags: list[str]
    created_at: datetime
    visual_search: VisualSearchRead | None = None


class VisualUploadLimits(BaseModel):
    max_bytes: int
    max_video_duration_seconds: float
    max_image_pixels: int
    max_video_pixels: int
    accepted_extensions: list[str]


class VisualAssetUpdate(BaseModel):
    """The creator's words about an asset; omitted fields are kept."""

    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(max_length=255)] | None = None
    description: Annotated[str, Field(max_length=DESCRIPTION_MAX_LENGTH * 2)] | None = None
    tags: (
        Annotated[
            list[Annotated[str, Field(max_length=TAG_MAX_LENGTH * 2)]],
            Field(max_length=TAGS_MAX * 2),
        ]
        | None
    ) = None
