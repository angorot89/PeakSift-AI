"""Audio asset responses. Never storage keys, file paths, hashes or probe internals."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class AudioAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    display_name: str
    content_type: str
    file_size: int
    duration_seconds: float
    sample_rate: int
    channels: int
    codec: str
    container: str
    created_at: datetime
    # V1.8 labels: how the creator may use it, local market, category, location (see
    # services/asset_labels.py).
    origin: str = "creator_upload"
    license_note: str | None = None
    market: str = "global"
    category: str | None = None
    location: str | None = None


class AudioWaveformRead(BaseModel):
    """Peak amplitude per bucket (0-100 % of full scale), evenly spread over the duration."""

    asset_id: uuid.UUID
    duration_seconds: float
    buckets: int
    peaks: list[int]


class AudioUploadLimits(BaseModel):
    max_bytes: int
    music_max_duration_seconds: float
    sfx_max_duration_seconds: float
    accepted_extensions: list[str]


class AudioAssetUpdate(BaseModel):
    """The creator's labels for a sound; omitted fields are kept. The file never changes."""

    model_config = ConfigDict(extra="forbid")

    origin: str | None = None
    license_note: Annotated[str, Field(max_length=600)] | None = None
    market: str | None = None
    category: str | None = None
    location: str | None = None
