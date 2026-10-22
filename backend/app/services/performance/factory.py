"""The configured performance provider (``PERFORMANCE_PROVIDER``)."""

from functools import cache

from app.core.config import Settings
from app.services.performance.provider import PerformanceProvider


@cache
def _fake():
    from app.services.performance.fake import FakeMetricsProvider

    return FakeMetricsProvider()  # one per process, so simulated videos stay consistent


def get_performance_provider(settings: Settings) -> PerformanceProvider:
    if settings.performance_provider == "fake":
        if settings.is_production:  # also refused at startup; never simulate in production
            raise RuntimeError("the fake performance provider is not available in production")
        return _fake()
    from app.services.performance.youtube import YouTubeMetricsProvider

    return YouTubeMetricsProvider.from_settings(settings)
