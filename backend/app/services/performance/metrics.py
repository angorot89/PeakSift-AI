"""The metric definitions PeakSift collects, and which definition applies to which day.

YouTube has redefined a "view" twice (see docs/performance-analytics.md for sources):

- **2025-03-31** — Shorts views count every start and replay, with no minimum watch time.
  ``engagedViews`` (added to the Analytics API on 2025-04-30) keeps the previous method.
- **2026-08-27** — public views of every format (long-form, Live, Shorts) count from the moment
  playback begins. ``engagedViews`` is unchanged.

So every daily row records ``metric_version`` — the view definition in force on that reporting
day — and comparisons across videos use ``engaged_views`` (a stable definition) and retention
metrics, never raw views across definitions. Watch time and retention exclude looping-clip
traffic since 2021-12-13 (before any PeakSift upload).

The reporting day is YouTube's Pacific-Time calendar day (``REPORTING_TIMEZONE``): processed
analytics arrive day by day, typically 2–3 days late, and never include the current day.
"""

from datetime import date
from zoneinfo import ZoneInfo

REPORTING_TIMEZONE = ZoneInfo("America/Los_Angeles")

SHORTS_STARTS_FROM = date(2025, 3, 31)
PLAYBACK_START_FROM = date(2026, 8, 27)

# The figures PeakSift stores (others the provider offers are never requested).
METRICS = (
    "views",
    "engaged_views",
    "likes",
    "comments",
    "watch_time_seconds",
    "average_view_duration_seconds",
    "average_view_percentage",
    "subscribers_gained",
)


def metric_version(day: date) -> str:
    """The YouTube view definition in force on ``day``."""
    if day >= PLAYBACK_START_FROM:
        return "youtube_views_2026_08"  # every format counts from playback start
    if day >= SHORTS_STARTS_FROM:
        return "youtube_views_2025_03"  # Shorts count starts and replays
    return "youtube_views_legacy"
