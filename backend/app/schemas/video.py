import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VideoRead(BaseModel):
    """Safe public view of a source video. Never includes storage keys or paths."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    content_type: str
    file_size: int
    status: str
    created_at: datetime
