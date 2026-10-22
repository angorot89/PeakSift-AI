"""The performance provider contract (YouTube is the only real implementation).

The sync pipeline talks to a provider only through this module's types, so it never sees an
HTTP response, a Google error or an SDK object:

- :meth:`PerformanceProvider.authorize` turns the stored refresh token into a short-lived,
  opaque ``ProviderAuth`` with the read-only analytics scopes (never persisted);
- :meth:`video_counters` reads the public counters and status of up to 50 videos in one call
  (YouTube Data API ``videos.list``). A video the provider no longer returns is simply absent
  from the result — the caller decides it is missing; it is never reported as zero views;
- :meth:`daily_metrics` reads one video's per-day analytics between two reporting dates
  (YouTube Analytics API, ``dimensions=day``). Days the provider has no data for are absent:
  **absence is not zero**, and a metric the provider did not report is ``None``.

Every number is validated here (finite, non-negative, the right type, dates inside the
requested range, no duplicate days) before it leaves the provider module.

Every failure is a :class:`PerformanceProviderError` with one of the normalized
:class:`PerformanceErrorCode` values and a message safe to show the creator.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from app.services.publishing.provider import ProviderAuth

# How many ids one counters call may carry (YouTube's videos.list limit).
MAX_VIDEOS_PER_CALL = 50


class PerformanceErrorCode(StrEnum):
    AUTHENTICATION_REQUIRED = "authentication_required"  # reconnect the account
    ANALYTICS_NOT_AUTHORIZED = "analytics_not_authorized"  # the read scopes were not granted
    API_NOT_ENABLED = "api_not_enabled"  # the operator's Google project lacks the API
    QUOTA_EXCEEDED = "quota_exceeded"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    PROVIDER_ERROR = "provider_error"  # 5xx or an unexpected answer
    INVALID_RESPONSE = "invalid_response"  # an answer that failed validation


RETRYABLE = frozenset(
    {PerformanceErrorCode.RATE_LIMITED, PerformanceErrorCode.NETWORK_ERROR,
     PerformanceErrorCode.PROVIDER_ERROR, PerformanceErrorCode.QUOTA_EXCEEDED}
)  # fmt: skip

USER_MESSAGES = {
    PerformanceErrorCode.AUTHENTICATION_REQUIRED: "YouTube needs you to reconnect your account",
    PerformanceErrorCode.ANALYTICS_NOT_AUTHORIZED: (
        "Analytics access is not connected for this YouTube account"
    ),
    PerformanceErrorCode.API_NOT_ENABLED: (
        "YouTube analytics is not available on this server's Google project"
    ),
    PerformanceErrorCode.QUOTA_EXCEEDED: "YouTube's daily quota is used up; metrics will resume",
    PerformanceErrorCode.RATE_LIMITED: "YouTube asked us to slow down; metrics will resume",
    PerformanceErrorCode.NETWORK_ERROR: "YouTube could not be reached; metrics will resume",
    PerformanceErrorCode.PROVIDER_ERROR: "YouTube had a problem; metrics will resume",
    PerformanceErrorCode.INVALID_RESPONSE: "YouTube returned metrics PeakSift could not verify",
}


class PerformanceProviderError(Exception):
    def __init__(self, code: PerformanceErrorCode) -> None:
        self.code = PerformanceErrorCode(code)
        self.message = USER_MESSAGES[self.code]
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE


@dataclass(frozen=True)
class VideoCounters:
    """Lifetime public counters and status of one video, as the provider reported them now.
    ``None``: the provider did not report it (for example hidden like counts)."""

    video_id: str
    views: int | None
    likes: int | None
    comments: int | None
    privacy: str | None
    upload_status: str | None


@dataclass(frozen=True)
class DailyMetrics:
    """One reporting day of one video. ``None``: not reported for that day."""

    day: date
    views: int | None = None
    engaged_views: int | None = None
    likes: int | None = None
    comments: int | None = None
    watch_time_seconds: int | None = None
    average_view_duration_seconds: float | None = None
    average_view_percentage: float | None = None
    subscribers_gained: int | None = None


class PerformanceProvider(Protocol):
    name: str  # "youtube" or "fake": becomes the stored data source

    def authorize(self, refresh_token: str) -> ProviderAuth: ...

    def video_counters(
        self, auth: ProviderAuth, video_ids: list[str]
    ) -> dict[str, VideoCounters]: ...

    def daily_metrics(
        self, auth: ProviderAuth, video_id: str, start: date, end: date
    ) -> list[DailyMetrics]: ...
