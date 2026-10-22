"""YouTube metrics: the Data API for counters and status, the Analytics API for daily rows.

- **Authorization:** the stored refresh token (granted by the creator's explicit analytics
  upgrade) is exchanged for an access token limited to ``youtube.readonly`` +
  ``yt-analytics.readonly`` per sync; it is never stored or logged.
- **Counters:** ``GET youtube/v3/videos?part=statistics,status&id=a,b,…`` (1 quota unit for up
  to 50 ids). A video YouTube does not return is absent from the result.
- **Daily analytics:** ``GET youtubeanalytics/v2/reports`` with ``ids=channel==MINE``,
  ``dimensions=day``, ``filters=video==<id>``, ``startDate``/``endDate`` (YouTube's reporting
  days, Pacific Time). Columns are read **by name from ``columnHeaders``**, never by position;
  YouTube omits rows for days without data (and data arrives with a delay of up to ~3 days),
  so a missing day stays missing — never zero.
- **Validation:** every count must be a non-negative integer, every average finite and
  non-negative, every day a real date inside the requested range, at most once. Anything
  else is :attr:`~PerformanceErrorCode.INVALID_RESPONSE`; nothing is clamped or repaired.
- **Errors** are normalized from the HTTP status and Google's reasons. Google's messages and
  response bodies never leave this module and are never logged.
"""

import logging
import math
import re
from collections.abc import Callable
from datetime import date

import httpx

from app.core.config import Settings
from app.services.performance.provider import (
    MAX_VIDEOS_PER_CALL,
    DailyMetrics,
    PerformanceErrorCode,
    PerformanceProviderError,
    VideoCounters,
)
from app.services.publishing.provider import ProviderAuth, PublishErrorCode, PublishProviderError
from app.services.publishing.youtube import _refresh_with_google
from app.services.publishing.youtube_oauth import ANALYTICS_SCOPES

logger = logging.getLogger(__name__)

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
REPORTS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
MAX_COUNT = 10**15  # far above any real count; larger is a broken answer

# Analytics column → (our field, kind). "minutes" become whole seconds.
COLUMNS = {
    "views": ("views", "count"),
    "engagedViews": ("engaged_views", "count"),
    "likes": ("likes", "count"),
    "comments": ("comments", "count"),
    "estimatedMinutesWatched": ("watch_time_seconds", "minutes"),
    "averageViewDuration": ("average_view_duration_seconds", "number"),
    "averageViewPercentage": ("average_view_percentage", "number"),
    "subscribersGained": ("subscribers_gained", "count"),
}
METRICS_PARAM = ",".join(COLUMNS)
PRIVACY = {"public", "private", "unlisted"}
UPLOAD_STATUS = {"uploaded", "processed", "failed", "rejected", "deleted"}

_QUOTA = {"quotaExceeded", "dailyLimitExceeded"}
_RATE = {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"}
_NOT_ENABLED = {"accessNotConfigured", "SERVICE_DISABLED"}
_PERMISSION = {"insufficientPermissions", "forbidden", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}
_AUTH = {"authError", "invalidCredentials", "unauthorized"}


def classify(status: int, reasons: set[str]) -> PerformanceErrorCode:
    if status == 401 or reasons & _AUTH:
        return PerformanceErrorCode.AUTHENTICATION_REQUIRED
    if reasons & _NOT_ENABLED:
        return PerformanceErrorCode.API_NOT_ENABLED
    if reasons & _QUOTA:
        return PerformanceErrorCode.QUOTA_EXCEEDED
    if status == 429 or reasons & _RATE:
        return PerformanceErrorCode.RATE_LIMITED
    if status == 403 or reasons & _PERMISSION:
        return PerformanceErrorCode.ANALYTICS_NOT_AUTHORIZED
    return PerformanceErrorCode.PROVIDER_ERROR


def _reasons(response: httpx.Response) -> set[str]:
    """Google's machine reasons, from both error formats (``errors[].reason`` and the newer
    ``details[].reason``). Never the human message."""
    try:
        error = response.json().get("error", {})
        found = {e.get("reason") for e in error.get("errors", []) if isinstance(e, dict)}
        found |= {d.get("reason") for d in error.get("details", []) if isinstance(d, dict)}
        return {str(reason) for reason in found if reason}
    except (ValueError, AttributeError):
        return set()


def _invalid(what: str) -> PerformanceProviderError:
    logger.warning("YouTube metrics failed validation: %s", what)
    return PerformanceProviderError(PerformanceErrorCode.INVALID_RESPONSE)


def _count(value, what: str) -> int | None:
    """Data API counts are decimal strings; Analytics counts are JSON integers."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise _invalid(what)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    elif isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or not 0 <= value <= MAX_COUNT:
        raise _invalid(what)
    return value


def _number(value, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(what)
    value = float(value)
    if not math.isfinite(value) or value < 0 or value > MAX_COUNT:
        raise _invalid(what)
    return value


def _check_id(video_id: str) -> str:
    if not isinstance(video_id, str) or not VIDEO_ID.match(video_id):
        raise ValueError("not a YouTube video id")
    return video_id


def parse_counters(payload, requested: set[str]) -> dict[str, VideoCounters]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items", []), list):
        raise _invalid("videos.list shape")
    result: dict[str, VideoCounters] = {}
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("id") not in requested:
            raise _invalid("videos.list item")
        stats = item.get("statistics") or {}
        status = item.get("status") or {}
        if not isinstance(stats, dict) or not isinstance(status, dict):
            raise _invalid("videos.list parts")
        privacy, upload = status.get("privacyStatus"), status.get("uploadStatus")
        result[item["id"]] = VideoCounters(
            video_id=item["id"],
            views=_count(stats.get("viewCount"), "viewCount"),
            likes=_count(stats.get("likeCount"), "likeCount"),
            comments=_count(stats.get("commentCount"), "commentCount"),
            privacy=privacy if privacy in PRIVACY else None,
            upload_status=upload if upload in UPLOAD_STATUS else None,
        )
    return result


def parse_report(payload, start: date, end: date) -> list[DailyMetrics]:
    if not isinstance(payload, dict):
        raise _invalid("report shape")
    headers = payload.get("columnHeaders")
    if not isinstance(headers, list) or not all(isinstance(h, dict) for h in headers):
        raise _invalid("columnHeaders")
    names = [h.get("name") for h in headers]
    if names.count("day") != 1 or len(set(names)) != len(names):
        raise _invalid("columnHeaders names")
    rows = payload.get("rows") or []  # YouTube omits "rows" when there is no data
    if not isinstance(rows, list):
        raise _invalid("rows")
    seen: set[date] = set()
    days: list[DailyMetrics] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(names):
            raise _invalid("row width")
        cells = dict(zip(names, row, strict=True))
        try:
            day = date.fromisoformat(cells["day"])
        except (TypeError, ValueError):
            raise _invalid("row day") from None
        if not start <= day <= end or day in seen:
            raise _invalid("row day range")
        seen.add(day)
        values: dict = {}
        for column, (name, kind) in COLUMNS.items():
            if column not in cells:
                continue
            if kind == "count":
                values[name] = _count(cells[column], column)
            else:
                number = _number(cells[column], column)
                if kind == "minutes" and number is not None:
                    number = round(number * 60)
                values[name] = number
        days.append(DailyMetrics(day=day, **values))
    return sorted(days, key=lambda d: d.day)


class YouTubeMetricsProvider:
    name = "youtube"

    def __init__(
        self,
        refresh: Callable[[str], str],
        *,
        client: httpx.Client | None = None,
        videos_url: str = VIDEOS_URL,
        reports_url: str = REPORTS_URL,
    ) -> None:
        self._refresh = refresh
        self._client = client or httpx.Client(timeout=httpx.Timeout(30, connect=10))
        self._videos_url = videos_url
        self._reports_url = reports_url

    @classmethod
    def from_settings(cls, settings: Settings) -> "YouTubeMetricsProvider":
        return cls(_refresh_with_google(settings, ANALYTICS_SCOPES))

    def _get(self, url: str, auth: ProviderAuth, params: dict) -> dict:
        try:
            response = self._client.get(
                url, params=params, headers={"Authorization": f"Bearer {auth.access_token}"}
            )
        except httpx.HTTPError as error:
            logger.warning("YouTube metrics request failed: %s", type(error).__name__)
            raise PerformanceProviderError(PerformanceErrorCode.NETWORK_ERROR) from None
        if response.status_code >= 400:
            reasons = _reasons(response)
            code = classify(response.status_code, reasons)
            logger.warning(
                "YouTube metrics answered %s (%s): %s",
                response.status_code,
                ",".join(sorted(reasons)) or "no reason",
                code,
            )
            raise PerformanceProviderError(code)
        try:
            return response.json()
        except ValueError:
            raise _invalid("not JSON") from None

    # --- the contract ----------------------------------------------------------------------

    def authorize(self, refresh_token: str) -> ProviderAuth:
        if not refresh_token:
            raise PerformanceProviderError(PerformanceErrorCode.AUTHENTICATION_REQUIRED)
        try:
            return ProviderAuth(self._refresh(refresh_token))
        except PublishProviderError as error:
            if error.code == PublishErrorCode.NETWORK_ERROR:
                raise PerformanceProviderError(PerformanceErrorCode.NETWORK_ERROR) from None
            if error.code == PublishErrorCode.PERMISSION_DENIED:  # the read scopes are missing
                raise PerformanceProviderError(
                    PerformanceErrorCode.ANALYTICS_NOT_AUTHORIZED
                ) from None
            raise PerformanceProviderError(PerformanceErrorCode.AUTHENTICATION_REQUIRED) from None

    def video_counters(self, auth: ProviderAuth, video_ids: list[str]) -> dict[str, VideoCounters]:
        ids = [_check_id(video_id) for video_id in dict.fromkeys(video_ids)]
        if not ids:
            return {}
        if len(ids) > MAX_VIDEOS_PER_CALL:
            raise ValueError("too many videos for one call")
        payload = self._get(
            self._videos_url, auth, {"part": "statistics,status", "id": ",".join(ids)}
        )
        return parse_counters(payload, set(ids))

    def daily_metrics(
        self, auth: ProviderAuth, video_id: str, start: date, end: date
    ) -> list[DailyMetrics]:
        if start > end:
            raise ValueError("start after end")
        params = {
            "ids": "channel==MINE",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "metrics": METRICS_PARAM,
            "dimensions": "day",
            "filters": f"video=={_check_id(video_id)}",
            "sort": "day",
        }
        return parse_report(self._get(self._reports_url, auth, params), start, end)
