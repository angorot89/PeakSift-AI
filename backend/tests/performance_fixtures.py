"""Plain helpers (not fixtures) for performance analytics tests: creators who granted analytics
access, published videos with chosen provenance, and fixed reporting days."""

import itertools
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import PublishedContent, PublishingConnection, User
from app.services.performance.provenance import PROVENANCE_VERSION
from app.services.publishing import connections
from app.services.publishing.youtube_oauth import ANALYTICS_SCOPE, READONLY_SCOPE, UPLOAD_SCOPE
from tests.publishing_fixtures import CIPHER, KEY, REFRESH_TOKEN, ready_edit

# 18:00 UTC is 11:00 in Los Angeles: the same reporting day either way.
NOW = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)
_ids = itertools.count(1)


def analytics_settings(**overrides) -> Settings:
    return Settings(**{
        **get_settings().model_dump(),
        "publishing_token_encryption_key": KEY, "youtube_analytics_enabled": True,
        "youtube_publishing_enabled": True, "performance_provider": "fake",
        "google_client_id": "1234-test.apps.googleusercontent.com",
        "google_client_secret": "GOCSPX-test", "performance_manual_cooldown_seconds": 900,
        "google_oauth_redirect_uri": "http://localhost:8000/publishing/youtube/callback",
        **overrides,
    })  # fmt: skip


def grant(db: Session, user: User, *, analytics: bool = True) -> PublishingConnection:
    scopes = [UPLOAD_SCOPE, READONLY_SCOPE, ANALYTICS_SCOPE] if analytics else [UPLOAD_SCOPE]
    return connections.save_connection(
        db, CIPHER, user_id=user.id, refresh_token=REFRESH_TOKEN, account_id="",
        account_title="Channel", scopes=scopes,
    )  # fmt: skip


def creator(db: Session) -> tuple[User, object]:
    """A user with one project (from a ready edit) whose videos tests can add."""
    user, edit = ready_edit(db)
    return user, edit


def make_content(
    db: Session,
    user: User,
    edit,
    *,
    published_at: datetime,
    provenance: dict | None = None,
    remote_video_id: str | None = None,
    **fields,
) -> PublishedContent:
    values = {
        "user_id": user.id, "project_id": edit.clip.video.project_id, "clip_id": edit.clip_id,
        "provider": "youtube", "remote_video_id": remote_video_id or f"simVideo{next(_ids):04d}",
        "title": "A short", "published_at": published_at, "duration_seconds": 20.0,
        "privacy": "public", "remote_status": "unknown", "provenance": provenance or {},
        "provenance_version": PROVENANCE_VERSION,
    }  # fmt: skip
    content = PublishedContent(**{**values, **fields})
    db.add(content)
    db.commit()
    return content
