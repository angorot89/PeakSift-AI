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


def signed_in_creator(db: Session, client, email: str | None = None) -> tuple[User, object]:
    """A creator signed in on ``client``, owning one project with a ready edit."""
    import uuid

    from tests.test_video_upload import sign_up

    client.cookies.clear()
    me = sign_up(client, email or f"analytics-{uuid.uuid4().hex[:8]}@example.com")
    user = db.get(User, uuid.UUID(me["id"]))
    _, edit = ready_edit(db)
    edit.clip.video.project.user_id = user.id
    db.commit()
    return user, edit


def with_week(
    db: Session,
    content: PublishedContent,
    engaged_per_day: int,
    retention: float = 50.0,
    *,
    source: str = "fake",
) -> PublishedContent:
    """Seven settled, fully reported days and a counter snapshot, with chosen figures."""
    from datetime import timedelta

    from app.models import PerformanceDailyMetric, PerformanceSnapshot
    from app.services.performance.metrics import metric_version, reporting_today

    first = reporting_today(content.published_at)
    for n in range(7):
        day = first + timedelta(n)
        db.add(PerformanceDailyMetric(
            content_id=content.id, source=source, date=day, metric_version=metric_version(day),
            views=engaged_per_day + 10, engaged_views=engaged_per_day, likes=5, comments=1,
            watch_time_seconds=600.0, average_view_duration_seconds=10.0,
            average_view_percentage=retention, subscribers_gained=0,
        ))  # fmt: skip
    db.add(PerformanceSnapshot(
        content_id=content.id, source=source, data_class="counters", observed_at=NOW,
        metric_version=metric_version(first), views=engaged_per_day * 7,
    ))  # fmt: skip
    content.analytics_complete_through = first + timedelta(10)
    content.remote_status = "active"
    db.commit()
    return content


def provenance(captions: str | None = "bold", hook: bool = False, auto: bool = False) -> dict:
    return {
        "recipe": "punchy" if auto else "manual",
        "auto_edit": {"used": auto, "planner": "rules" if auto else None},
        "layout": "center_crop",
        "captions": {"enabled": captions is not None, "preset": captions, "position": "bottom"},
        "hook": {"enabled": hook, "length_chars": 20 if hook else 0},
        "visuals": {"count": 0, "cutaways": 0, "pips": 0, "overlays": 0},
        "audio": {"music": False, "ducking": None, "sfx_count": 0, "normalized": False},
        "candidate": {"rank": 1, "score": 70, "category": "story"},
    }
