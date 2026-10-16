import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PublishingConnectionRead(BaseModel):
    """What the user may see about their connection: never tokens or scopes' internals."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    status: str
    # Empty until the first upload reports the channel (no read scope is requested).
    account_title: str
    connected_at: datetime


class YouTubeStatusRead(BaseModel):
    enabled: bool
    connection: PublishingConnectionRead | None


class AuthorizationRead(BaseModel):
    authorization_url: str


class DisconnectRead(BaseModel):
    revoked_with_provider: bool


class PublishRequest(BaseModel):
    """What the user reviewed in the publish dialog. Validated by YouTube's rules; never
    truncated (see services/publishing/metadata.py)."""

    title: str = Field(max_length=1000)
    description: str = Field(default="", max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=200)
    privacy: str = "private"
    made_for_kids: bool = False


class PublishDefaults(BaseModel):
    title: str
    description: str
    tags: list[str]
    privacy: str
    made_for_kids: bool


class PublishJobRead(BaseModel):
    """A publish job as the owner sees it: never tokens, session URIs, task ids or keys."""

    id: uuid.UUID
    edit_id: uuid.UUID
    provider: str
    status: str
    progress_percent: int
    bytes_uploaded: int
    bytes_total: int | None
    title: str
    description: str
    tags: list[str]
    privacy: str
    made_for_kids: bool
    # Links to the video on YouTube, once it exists (absent for simulated uploads).
    video_url: str | None
    studio_url: str | None
    simulated: bool
    error_code: str | None
    error_message: str | None
    retryable: bool
    is_stale: bool
    # True while YouTube's processing is still being checked; false once it is known or
    # cannot be known (the upload-only scope cannot read processing).
    awaiting_processing: bool
    attempt: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    published_at: datetime | None


class PublishPanelRead(BaseModel):
    """Everything the publish dialog needs for one edit."""

    enabled: bool
    connection: PublishingConnectionRead | None
    edit_ready: bool
    defaults: PublishDefaults
    jobs: list[PublishJobRead]
