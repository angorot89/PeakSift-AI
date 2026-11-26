"""Publishing to more than one platform: a connection per platform, a provider per job, refresh
tokens that rotate, messages in the platform's own name, and the platform list."""

import io
import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import publishing as api
from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.models import PublishingConnection, PublishingProvider, PublishStatus
from app.models.publishing_connection import PROVIDER_CHECK
from app.services.publishing import connections, pipeline, platforms
from app.services.publishing.factory import get_publishing_provider
from app.services.publishing.fake import FakePublishingProvider
from app.services.publishing.jobs import request_publish
from app.services.publishing.metadata import PublishMetadata
from app.services.publishing.provider import (
    PublishErrorCode,
    PublishProviderError,
    user_message,
)
from app.services.publishing.tokens import TokenDecryptionError
from app.services.storage import LocalStorageProvider
from tests.publishing_fixtures import CIPHER, KEY, REFRESH_TOKEN, connect, new_user, ready_edit

CHUNK = 256 * 1024
DATA = os.urandom(CHUNK + 999)


def tiktok(db: Session, user, token: str = "tiktok-refresh-1") -> PublishingConnection:
    return connections.save_connection(
        db, CIPHER, user_id=user.id, refresh_token=token, account_id="open-id-1",
        account_title="@creator", scopes=["video.publish"], provider=PublishingProvider.TIKTOK,
    )  # fmt: skip


# --- a connection per platform ----------------------------------------------------------


def test_a_creator_can_connect_several_platforms(db_session: Session):
    user = new_user(db_session)
    youtube = connect(db_session, user)
    other = tiktok(db_session, user)

    assert youtube.id != other.id
    assert connections.get_connection(db_session, user.id).id == youtube.id  # YouTube by default
    assert connections.get_connection(db_session, user.id, PublishingProvider.TIKTOK).id == other.id
    assert connections.get_connection(db_session, user.id, "tiktok").id == other.id
    assert set(connections.list_connections(db_session, user.id)) == {"youtube", "tiktok"}
    assert connections.list_connections(db_session, new_user(db_session).id) == {}


def test_reconnecting_replaces_only_that_platform(db_session: Session):
    user = new_user(db_session)
    youtube = connect(db_session, user)
    first = tiktok(db_session, user)

    second = tiktok(db_session, user, "tiktok-refresh-2")

    assert second.id == first.id
    assert connections.refresh_token_of(db_session, CIPHER, second) == "tiktok-refresh-2"
    assert connections.refresh_token_of(db_session, CIPHER, youtube) == REFRESH_TOKEN
    assert len(connections.list_connections(db_session, user.id)) == 2


def test_a_token_is_bound_to_its_platform(db_session: Session):
    """Copying one platform's ciphertext onto another's row must not decrypt."""
    user = new_user(db_session)
    youtube, other = connect(db_session, user), tiktok(db_session, user)
    other.refresh_token_ciphertext = youtube.refresh_token_ciphertext
    db_session.commit()

    with pytest.raises(TokenDecryptionError):
        connections.refresh_token_of(db_session, CIPHER, other)


def test_only_known_platforms_can_be_stored(db_session: Session):
    assert {p.value for p in PublishingProvider} == {"youtube", "tiktok", "instagram"}
    for provider in PublishingProvider:
        assert f"'{provider.value}'" in PROVIDER_CHECK  # the constraint and the enum agree
    user = new_user(db_session)
    youtube = connect(db_session, user)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE publishing_connections SET provider = 'myspace' WHERE id = :id"),
            {"id": youtube.id},
        )
    db_session.rollback()


def test_disconnecting_one_platform_keeps_the_other(db_session: Session):
    user = new_user(db_session)
    connect(db_session, user)
    other = tiktok(db_session, user)
    revoked: list[str] = []

    assert connections.disconnect(db_session, CIPHER, other, revoked.append) is True

    assert revoked == ["tiktok-refresh-1"]
    assert set(connections.list_connections(db_session, user.id)) == {"youtube"}


# --- rotating refresh tokens --------------------------------------------------------------


def test_a_rotated_token_replaces_the_stored_one(db_session: Session):
    user = new_user(db_session)
    connection = tiktok(db_session, user)

    connections.store_rotated_token(db_session, CIPHER, connection, "tiktok-refresh-next")

    db_session.expire_all()
    stored = connections.get_connection(db_session, user.id, "tiktok")
    assert connections.refresh_token_of(db_session, CIPHER, stored) == "tiktok-refresh-next"


class RotatingProvider(FakePublishingProvider):
    """A platform that issues a new refresh token every time one is used."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def authorize(self, refresh_token: str):
        self.seen.append(refresh_token)
        auth = super().authorize(refresh_token)
        return replace(auth, rotated_refresh_token=f"rotated-{len(self.seen)}")


def test_the_pipeline_keeps_the_token_a_platform_rotated(db_session: Session, tmp_path):
    settings = Settings(**{**get_settings().model_dump(), "publishing_token_encryption_key": KEY,
                           "youtube_upload_chunk_bytes": CHUNK})  # fmt: skip
    storage = LocalStorageProvider(tmp_path / "media")
    user, edit = ready_edit(db_session)
    storage.save(io.BytesIO(DATA), edit.storage_key)
    connection = connect(db_session, user)
    job, _ = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connection, task_id="task-1",
        metadata=PublishMetadata.create(title="Rotation"),
    )  # fmt: skip
    provider = RotatingProvider()

    pipeline.publish_short(job.id, db_session, settings=settings, storage=storage,
                           provider=provider, task_id="task-1", sleep=lambda s: None)  # fmt: skip

    assert job.status in (PublishStatus.UPLOADED, PublishStatus.PROCESSING, PublishStatus.PUBLISHED)
    assert provider.seen[0] == REFRESH_TOKEN
    assert connections.refresh_token_of(db_session, CIPHER, connection) == "rotated-1"

    # The next use (a processing check) authorizes with the rotated token, not the dead one.
    pipeline.check_status(job.id, db_session, settings=settings, provider=provider)
    if len(provider.seen) > 1:
        assert provider.seen[1] == "rotated-1"
        assert connections.refresh_token_of(db_session, CIPHER, connection) == "rotated-2"


# --- providers and messages -----------------------------------------------------------


def test_each_job_gets_its_platforms_provider():
    real = Settings(**{**get_settings().model_dump(), "publishing_provider": "youtube"})
    with pytest.raises(RuntimeError, match="no publishing provider"):
        get_publishing_provider(real, "myspace")

    simulated = Settings(**{**get_settings().model_dump(), "publishing_provider": "fake"})
    assert get_publishing_provider(simulated, "youtube") is get_publishing_provider(
        simulated, "tiktok"
    )


def test_messages_name_the_platform():
    assert user_message(PublishErrorCode.NETWORK_ERROR) == "YouTube could not be reached; try again"
    assert user_message(PublishErrorCode.NETWORK_ERROR, "TikTok").startswith("TikTok could not")
    assert "channel" in user_message(PublishErrorCode.PERMISSION_DENIED)  # YouTube's own wording
    assert "channel" not in user_message(PublishErrorCode.PERMISSION_DENIED, "TikTok")
    error = PublishProviderError(PublishErrorCode.QUOTA_EXCEEDED, platform="TikTok")
    assert error.message.startswith("TikTok's upload quota") and not error.retryable
    for code in PublishErrorCode:
        assert "{" not in user_message(code, "TikTok")


def test_the_registry_lists_only_working_platforms():
    assert [platform.key for platform in platforms.PLATFORMS] == ["youtube", "tiktok", "instagram"]
    assert platforms.label("youtube") == "YouTube" and platforms.label("tiktok") == "TikTok"
    assert platforms.get("myspace") is None and platforms.label("myspace") == "Myspace"
    for platform in platforms.PLATFORMS:
        assert platform.key in {p.value for p in PublishingProvider}


# --- the API ------------------------------------------------------------------------------


def sign_in(client: TestClient, user_id) -> None:
    client.cookies.clear()
    client.cookies.set(get_settings().auth_cookie_name, create_access_token(user_id))


@pytest.mark.parametrize("enabled", [True, False])
def test_platforms_endpoint_lists_platforms_and_the_creators_connections(
    client: TestClient, db_session: Session, monkeypatch, enabled
):
    configured = Settings(**{**get_settings().model_dump(), "youtube_publishing_enabled": enabled,
                             "publishing_token_encryption_key": KEY,
                             "google_client_id": "x.apps.googleusercontent.com",
                             "google_client_secret": "s",
                             "google_oauth_redirect_uri":
                                 "http://localhost:8000/publishing/youtube/callback"})  # fmt: skip
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    assert client.get("/publishing/platforms").status_code == 401

    user = new_user(db_session)
    sign_in(client, user.id)
    youtube, tiktok_row, instagram_row = client.get("/publishing/platforms").json()
    assert youtube == {"key": "youtube", "label": "YouTube", "account_noun": "channel",
                       "enabled": enabled, "connection": None}  # fmt: skip
    # TikTok is listed, and honestly marked as not set up on this server.
    assert tiktok_row == {"key": "tiktok", "label": "TikTok", "account_noun": "account",
                          "enabled": False, "connection": None}  # fmt: skip
    assert instagram_row == {"key": "instagram", "label": "Instagram", "account_noun": "account",
                             "enabled": False, "connection": None}  # fmt: skip

    connect(db_session, user)
    response = client.get("/publishing/platforms")
    connection = response.json()[0]["connection"]
    assert connection["provider"] == "youtube" and connection["status"] == "connected"
    assert set(connection) == {"provider", "status", "account_title", "connected_at",
                               "analytics_access"}  # fmt: skip
    assert REFRESH_TOKEN not in response.text and "scopes" not in response.text

    # Another creator sees the platform, never this creator's connection.
    sign_in(client, new_user(db_session).id)
    assert client.get("/publishing/platforms").json()[0]["connection"] is None
