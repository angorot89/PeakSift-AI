import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.services.publishing.youtube_oauth import has_analytics_access


class PublishingConnectionRead(BaseModel):
    """What the user may see about their connection: never tokens or scopes' internals."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    status: str
    # Empty until the first upload reports the channel (no read scope is requested).
    account_title: str
    connected_at: datetime
    scopes: str = Field(exclude=True)

    @computed_field
    @property
    def analytics_access(self) -> bool:
        """Whether the creator granted the read-only analytics upgrade."""
        return has_analytics_access(self.scopes)


class YouTubeStatusRead(BaseModel):
    enabled: bool
    # Whether this server offers performance analytics (the creator still opts in).
    analytics_enabled: bool = False
    connection: PublishingConnectionRead | None


class PlatformRead(BaseModel):
    """A platform PeakSift can publish to, and the creator's connection to it (if any)."""

    key: str
    label: str
    account_noun: str
    # This server is set up for it; when false the creator cannot connect yet.
    enabled: bool
    connection: PublishingConnectionRead | None


class TikTokStatusRead(BaseModel):
    enabled: bool
    connection: PublishingConnectionRead | None


class TikTokCreatorRead(BaseModel):
    """What TikTok offers this creator for a post right now (shown as-is in the dialog)."""

    nickname: str
    username: str
    privacy_levels: list[str]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_duration_seconds: int | None


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
    # Publish at this time instead of now (with its time zone; at least a few minutes ahead).
    scheduled_at: datetime | None = None
    # Where it goes ("youtube" when left out) and what the creator chose that only that
    # platform has. For TikTok: privacy_level, allow_comment, allow_duet, allow_stitch,
    # commercial, brand_organic, brand_content, music_usage_confirmed.
    platform: str = Field(default="youtube", max_length=16)
    options: dict[str, bool | str | None] = Field(default_factory=dict, max_length=16)


class ScheduleChange(BaseModel):
    scheduled_at: datetime


class CalendarItem(BaseModel):
    """One post on the calendar: a publish job with the Short it belongs to."""

    job: "PublishJobRead"
    # Where it sits on the calendar: its scheduled time, else when it was published or started.
    at: datetime
    short_title: str
    project_id: uuid.UUID
    project_name: str
    clip_id: uuid.UUID


class CalendarRead(BaseModel):
    items: list[CalendarItem]
    # Scheduled posts need the scheduler (Celery beat); the UI says so when it cannot tell.
    connection_ready: bool


class PostingSlot(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    time: str = Field(pattern=r"^\d{2}:\d{2}$")


class PostingSlotsUpdate(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)  # an IANA name, from the browser
    slots: list[PostingSlot] = Field(max_length=100)


class PostingSlotsRead(BaseModel):
    timezone: str | None
    slots: list[PostingSlot]
    # The next free slot times (UTC): not in the past and not taken by a scheduled post.
    upcoming: list[datetime]


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
    # When the creator asked for it to go out (null for a job published right away).
    scheduled_at: datetime | None = None
    # What the creator chose that only this platform has (empty for YouTube).
    options: dict[str, bool | str | None] = Field(default_factory=dict)


class PublishPanelRead(BaseModel):
    """Everything the publish dialog needs for one edit."""

    enabled: bool
    connection: PublishingConnectionRead | None
    edit_ready: bool
    defaults: PublishDefaults
    jobs: list[PublishJobRead]
    # Which platform this panel is for.
    platform: str = "youtube"


CalendarItem.model_rebuild()
