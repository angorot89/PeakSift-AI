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
    # V1.8 labels: how the creator may use it, local market, category, location (see
    # services/asset_labels.py).
    origin: str = "creator_upload"
    license_note: str | None = None
    market: str = "global"
    category: str | None = None
    location: str | None = None


class VisualMatchRead(BaseModel):
    """Why an asset was found: a strength tier and the signal — never a score or percentage."""

    strength: str  # strong / possible
    method: str  # visual (what it shows) / metadata (name, description, tags) / both
    best_frame_time: float | None = None  # videos found by what they show: the best scene (s)


class VisualSearchHit(BaseModel):
    asset: VisualAssetRead
    match: VisualMatchRead
    # In a local market's project: the asset is local to that market (shown first in its tier).
    local: bool = False


class VisualSearchResults(BaseModel):
    query: str  # the cleaned query that was searched
    visual_search_used: bool  # False: names, descriptions and tags only
    assets_preparing: int  # assets not yet searchable by what they show
    results: list[VisualSearchHit]


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
    origin: str | None = None
    license_note: Annotated[str, Field(max_length=600)] | None = None
    market: str | None = None
    category: str | None = None
    location: str | None = None
