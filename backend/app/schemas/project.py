import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ProjectCreate(BaseModel):
    name: ProjectName
    # Optional: the creator's default market and "auto" language when left out.
    market: str | None = None
    content_language: str | None = None


class ProjectUpdate(BaseModel):
    """An explicit change by the creator. Existing Shorts keep the market they were made with."""

    market: str | None = None
    content_language: str | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    market: str = "global"
    content_language: str = "auto"
    created_at: datetime
    updated_at: datetime


class ProjectDelete(BaseModel):
    # Explicit confirmation: the project's exact name, typed by the user.
    confirm_name: str = Field(max_length=200)


class MediaDeletionRead(BaseModel):
    """What happened to the media files. Files that could not be removed now are left for
    the storage cleanup; they are no longer reachable through the API."""

    media_files_removed: int
    media_files_pending_cleanup: int
