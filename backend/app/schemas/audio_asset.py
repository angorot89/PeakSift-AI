"""Audio asset responses. Never storage keys, file paths, hashes or probe internals."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
