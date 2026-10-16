from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
