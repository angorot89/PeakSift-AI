"""Deterministic simulated metrics for tests and non-production stacks.

``PERFORMANCE_PROVIDER=fake`` (refused in production) replaces YouTube with this provider.
Everything it returns is stored with ``source="fake"`` and shown as **simulated** — it must
never pass for a creator's real data. Nothing leaves the process.

Each video gets a reproducible series from a hash of its id: a first-day peak decaying day by
day, engaged views below views, retention, likes, comments and subscribers in plausible
proportions. Like YouTube, it reports only days that have been processed (``lag_days`` behind
"today" in Pacific Time), omits days before the video existed, can hide like counts, can lose a
video (deleted on the platform) and can fail any call on demand.
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.services.performance.metrics import reporting_today
from app.services.performance.provider import (
    DailyMetrics,
    PerformanceErrorCode,
    PerformanceProviderError,
    VideoCounters,
)
from app.services.publishing.provider import ProviderAuth


@dataclass
class FakeVideo:
    published: date
    scale: float = 1.0  # multiplies views (used by synthetic fixtures to create patterns)
    retention: float | None = None  # average view percentage; None: derived from the id
    hide_likes: bool = False
    privacy: str = "public"


def _seed(video_id: str) -> int:
    return int.from_bytes(hashlib.sha256(video_id.encode()).digest()[:8], "big")


class FakeMetricsProvider:
    name = "fake"

    def __init__(self, *, today: Callable[[], date] = reporting_today, lag_days: int = 2):
        self.today = today
        self.lag_days = lag_days
        self.videos: dict[str, FakeVideo] = {}
        self.missing: set[str] = set()
        self.calls: list[str] = []
        self._failures: dict[str, list[PerformanceErrorCode | None]] = defaultdict(list)

    # --- scripting ------------------------------------------------------------------------

    def register(self, video_id: str, published: date, **options) -> FakeVideo:
        self.videos[video_id] = FakeVideo(published, **options)
        self.missing.discard(video_id)
        return self.videos[video_id]

    def delete(self, video_id: str) -> None:
        """The creator deleted the video on the platform."""
        self.missing.add(video_id)

    def fail(self, operation: str, codes: Iterable[PerformanceErrorCode | None]) -> None:
        """The next calls of ``operation`` raise these codes in order (None: succeed)."""
        self._failures[operation].extend(codes)

    def _maybe_fail(self, operation: str) -> None:
        self.calls.append(operation)
        if self._failures[operation]:
            code = self._failures[operation].pop(0)
            if code is not None:
                raise PerformanceProviderError(code)

    def _video(self, video_id: str) -> FakeVideo:
        if video_id not in self.videos:  # first sight: published within the last four weeks
            self.videos[video_id] = FakeVideo(self.today() - timedelta(_seed(video_id) % 28))
        return self.videos[video_id]

    # --- the series -----------------------------------------------------------------------

    def day(self, video_id: str, day: date) -> DailyMetrics | None:
        video = self._video(video_id)
        age = (day - video.published).days
        if age < 0 or day > self.today() - timedelta(self.lag_days):
            return None  # before the video existed, or not processed yet
        seed = _seed(video_id)
        peak = (200 + seed % 4800) * video.scale
        wobble = 0.85 + ((seed >> (age % 32)) % 31) / 100
        views = int(peak * (0.62**age) * wobble) + (seed >> 3) % 4
        retention = video.retention if video.retention is not None else 45 + (seed >> 5) % 60
        duration = 15 + (seed >> 7) % 40
        return DailyMetrics(
            day=day,
            views=views,
            engaged_views=int(views * (0.7 + ((seed >> 9) % 25) / 100)),
            likes=None if video.hide_likes else int(views * (0.02 + ((seed >> 11) % 6) / 100)),
            comments=int(views * 0.004),
            watch_time_seconds=round(views * duration * retention / 100),
            average_view_duration_seconds=round(duration * retention / 100, 2) if views else 0.0,
            average_view_percentage=float(retention) if views else 0.0,
            subscribers_gained=int(views * 0.002),
        )

    # --- the contract ---------------------------------------------------------------------

    def authorize(self, refresh_token: str) -> ProviderAuth:
        self._maybe_fail("authorize")
        if not refresh_token:
            raise PerformanceProviderError(PerformanceErrorCode.AUTHENTICATION_REQUIRED)
        digest = hashlib.sha256(refresh_token.encode()).hexdigest()[:12]
        return ProviderAuth(f"fake-metrics-{digest}")

    def video_counters(self, auth: ProviderAuth, video_ids: list[str]) -> dict[str, VideoCounters]:
        self._maybe_fail("video_counters")
        result = {}
        for video_id in dict.fromkeys(video_ids):
            if video_id in self.missing:
                continue
            video = self._video(video_id)
            days = [
                self.day(video_id, video.published + timedelta(n))
                for n in range((self.today() - video.published).days + 1)
            ]
            known = [d for d in days if d is not None]
            result[video_id] = VideoCounters(
                video_id=video_id,
                views=sum(d.views for d in known),
                likes=None if video.hide_likes else sum(d.likes for d in known),
                comments=sum(d.comments for d in known),
                privacy=video.privacy,
                upload_status="processed",
            )
        return result

    def daily_metrics(
        self, auth: ProviderAuth, video_id: str, start: date, end: date
    ) -> list[DailyMetrics]:
        self._maybe_fail("daily_metrics")
        if start > end:
            raise ValueError("start after end")
        if video_id in self.missing:
            return []
        days = (self.day(video_id, start + timedelta(n)) for n in range((end - start).days + 1))
        return [d for d in days if d is not None]
