"""Performance providers: YouTube's Data and Analytics answers parsed by column name and
validated (absence is never zero, nothing is clamped), errors normalized without leaking
Google's messages or tokens, the deterministic fake, and configuration. No network: YouTube
is an ``httpx.MockTransport``."""

import json
import logging
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.services.performance import factory
from app.services.performance.fake import FakeMetricsProvider
from app.services.performance.provider import (
    DailyMetrics,
    PerformanceErrorCode,
    PerformanceProviderError,
)
from app.services.performance.youtube import YouTubeMetricsProvider
from app.services.publishing.provider import (
    ProviderAuth,
    PublishErrorCode,
    PublishProviderError,
)

TOKEN = "ya29.MetricsAccessToken"
AUTH = ProviderAuth(TOKEN)
VID = "dQw4w9WgXcQ"
START, END = date(2026, 10, 1), date(2026, 10, 20)
HEADERS = [
    {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
    {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
    {"name": "engagedViews", "columnType": "METRIC", "dataType": "INTEGER"},
    {"name": "estimatedMinutesWatched", "columnType": "METRIC", "dataType": "INTEGER"},
    {"name": "averageViewDuration", "columnType": "METRIC", "dataType": "INTEGER"},
    {"name": "averageViewPercentage", "columnType": "METRIC", "dataType": "FLOAT"},
    {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
    {"name": "comments", "columnType": "METRIC", "dataType": "INTEGER"},
    {"name": "subscribersGained", "columnType": "METRIC", "dataType": "INTEGER"},
]


class Google:
    """Records requests; answers with whatever the test set."""

    def __init__(self, status=200, body=None):
        self.status, self.body, self.requests = status, body, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, Exception):
            raise self.body
        content = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()
        return httpx.Response(self.status, content=content)

    def provider(self) -> YouTubeMetricsProvider:
        client = httpx.Client(transport=httpx.MockTransport(self))
        return YouTubeMetricsProvider(lambda token: TOKEN, client=client)


def report(rows, headers=HEADERS) -> dict:
    return {"kind": "youtubeAnalytics#resultTable", "columnHeaders": headers, "rows": rows}


# --- counters ----------------------------------------------------------------------------------


def test_counters_parse_strings_and_keep_hidden_counts_unknown():
    google = Google(body={"items": [
        {"id": VID, "statistics": {"viewCount": "1234", "likeCount": "56", "commentCount": "0"},
         "status": {"privacyStatus": "public", "uploadStatus": "processed"}},
        {"id": "abcdef12345", "statistics": {"viewCount": "7", "commentCount": "1"},
         "status": {"privacyStatus": "unlisted", "uploadStatus": "processed"}},
    ]})  # fmt: skip
    counters = google.provider().video_counters(AUTH, [VID, "abcdef12345", "gone0000000"])
    assert counters[VID].views == 1234 and counters[VID].comments == 0  # a real zero
    assert counters["abcdef12345"].likes is None  # hidden like count: unknown, not 0
    assert "gone0000000" not in counters  # absent: the caller decides it is missing
    [request] = google.requests
    assert request.url.params["part"] == "statistics,status"
    assert request.url.params["id"] == f"{VID},abcdef12345,gone0000000"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    "item",
    [
        {"id": VID, "statistics": {"viewCount": "-1"}},
        {"id": VID, "statistics": {"viewCount": "1e3"}},
        {"id": VID, "statistics": {"viewCount": True}},
        {"id": VID, "statistics": {"viewCount": "12.5"}},
        {"id": "notrequested", "statistics": {"viewCount": "1"}},
        {"id": VID, "statistics": ["1"]},
    ],
    ids=["negative", "exponent", "bool", "fraction", "unrequested", "shape"],
)
def test_counters_that_fail_validation_are_refused(item):
    with pytest.raises(PerformanceProviderError) as excinfo:
        Google(body={"items": [item]}).provider().video_counters(AUTH, [VID])
    assert excinfo.value.code == PerformanceErrorCode.INVALID_RESPONSE


def test_unknown_statuses_are_not_guessed():
    body = {"items": [{"id": VID, "statistics": {}, "status": {"privacyStatus": "secret"}}]}
    counters = Google(body=body).provider().video_counters(AUTH, [VID])[VID]
    assert counters.privacy is None and counters.views is None


@pytest.mark.parametrize("bad", ["a,b0000000", "x" * 65, "short", "id with space", ""])
def test_video_ids_are_checked_before_any_request(bad):
    google = Google(body={"items": []})
    with pytest.raises(ValueError):
        google.provider().video_counters(AUTH, [bad])
    with pytest.raises(ValueError):
        google.provider().daily_metrics(AUTH, bad, START, END)
    assert google.requests == []


def test_at_most_fifty_videos_per_call():
    with pytest.raises(ValueError):
        Google(body={}).provider().video_counters(AUTH, [f"video{n:06d}" for n in range(51)])
    assert Google(body={}).provider().video_counters(AUTH, []) == {}


# --- daily analytics ---------------------------------------------------------------------------


def test_the_report_request_is_one_video_by_day():
    google = Google(body=report([]))
    google.provider().daily_metrics(AUTH, VID, START, END)
    params = google.requests[0].url.params
    assert params["ids"] == "channel==MINE" and params["dimensions"] == "day"
    assert params["filters"] == f"video=={VID}" and params["sort"] == "day"
    assert (params["startDate"], params["endDate"]) == ("2026-10-01", "2026-10-20")
    assert set(params["metrics"].split(",")) == {
        "views", "engagedViews", "estimatedMinutesWatched", "averageViewDuration",
        "averageViewPercentage", "likes", "comments", "subscribersGained",
    }  # fmt: skip


def test_columns_are_read_by_name_not_position():
    shuffled = [HEADERS[3], HEADERS[0], HEADERS[1], HEADERS[5]]
    rows = [[30, "2026-10-02", 100, 54.5], [12, "2026-10-01", 40, 61.0]]
    days = Google(body=report(rows, shuffled)).provider().daily_metrics(AUTH, VID, START, END)
    assert days == [
        DailyMetrics(day=date(2026, 10, 1), views=40, watch_time_seconds=720,
                     average_view_percentage=61.0),
        DailyMetrics(day=date(2026, 10, 2), views=100, watch_time_seconds=1800,
                     average_view_percentage=54.5),
    ]  # fmt: skip
    assert days[0].engaged_views is None and days[0].likes is None  # not reported: unknown


def test_days_without_data_stay_missing_never_zero():
    days = Google(body={"kind": "youtubeAnalytics#resultTable", "columnHeaders": HEADERS})
    assert days.provider().daily_metrics(AUTH, VID, START, END) == []
    one = Google(body=report([["2026-10-05", 0, 0, 0, 0, 0.0, 0, 0, 0]]))
    [day] = one.provider().daily_metrics(AUTH, VID, START, END)
    assert day.day == date(2026, 10, 5) and day.views == 0  # a reported zero stays zero


def test_retention_above_one_hundred_percent_is_kept():
    body = report([["2026-10-05", 10, 8, 3, 40, 131.7, 1, 0, 0]])
    [day] = Google(body=body).provider().daily_metrics(AUTH, VID, START, END)
    assert day.average_view_percentage == 131.7 and day.average_view_duration_seconds == 40.0


@pytest.mark.parametrize(
    "body",
    [
        report([["2026-09-30", 1, 1, 1, 1, 1.0, 1, 1, 1]]),  # before the range
        report([["2026-10-21", 1, 1, 1, 1, 1.0, 1, 1, 1]]),  # after it
        report([["2026-10-02", 1, 1, 1, 1, 1.0, 1, 1, 1]] * 2),  # the same day twice
        report([["2026-10-02", 1, 1]]),  # a short row
        report([["yesterday", 1, 1, 1, 1, 1.0, 1, 1, 1]]),
        report([["2026-10-02", -3, 1, 1, 1, 1.0, 1, 1, 1]]),  # negative
        report([["2026-10-02", 1.5, 1, 1, 1, 1.0, 1, 1, 1]]),  # a fractional count
        report([["2026-10-02", 1, 1, 1, 1, "NaN", 1, 1, 1]]),
        report([["2026-10-02", 1, 1, 1, 1, float("inf"), 1, 1, 1]]),
        report([["2026-10-02", 1]], [HEADERS[1], HEADERS[1]]),  # duplicate columns, no day
        {"columnHeaders": "views"},
        [],
    ],
    ids=[
        "before",
        "after",
        "duplicate-day",
        "short-row",
        "bad-day",
        "negative",
        "fraction",
        "nan-string",
        "infinite",
        "headers",
        "header-shape",
        "not-an-object",
    ],  # fmt: skip
)
def test_reports_that_fail_validation_are_refused_not_repaired(body):
    content = json.dumps(body).replace("Infinity", "1e999").encode()  # JSON has no infinity
    with pytest.raises(PerformanceProviderError) as excinfo:
        Google(body=content).provider().daily_metrics(AUTH, VID, START, END)
    assert excinfo.value.code == PerformanceErrorCode.INVALID_RESPONSE


# --- errors ------------------------------------------------------------------------------------


def google_error(status, reason=None, detail=None, message="Secret Google message about x"):
    error = {"code": status, "message": message, "errors": [], "details": []}
    if reason:
        error["errors"].append({"reason": reason, "message": message})
    if detail:
        error["details"].append({"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                 "reason": detail})  # fmt: skip
    return {"error": error}


@pytest.mark.parametrize(
    ("status", "reason", "detail", "code", "retryable"),
    [
        (401, "authError", None, "authentication_required", False),
        (403, "insufficientPermissions", None, "analytics_not_authorized", False),
        (403, None, "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "analytics_not_authorized", False),
        (403, "forbidden", None, "analytics_not_authorized", False),
        (403, "accessNotConfigured", None, "api_not_enabled", False),
        (403, None, "SERVICE_DISABLED", "api_not_enabled", False),
        (403, "quotaExceeded", None, "quota_exceeded", True),
        (429, None, "RATE_LIMIT_EXCEEDED", "rate_limited", True),
        (500, "backendError", None, "provider_error", True),
        (400, "badRequest", None, "provider_error", True),
    ],
)
def test_google_errors_are_normalized(status, reason, detail, code, retryable, caplog):
    caplog.set_level(logging.DEBUG)
    google = Google(status, google_error(status, reason, detail))
    for call in (lambda p: p.video_counters(AUTH, [VID]),
                 lambda p: p.daily_metrics(AUTH, VID, START, END)):  # fmt: skip
        with pytest.raises(PerformanceProviderError) as excinfo:
            call(google.provider())
        assert excinfo.value.code == code and excinfo.value.retryable is retryable
        assert "Secret Google message" not in excinfo.value.message
    assert "Secret Google message" not in caplog.text and TOKEN not in caplog.text


def test_network_failures_and_garbage_are_normalized():
    with pytest.raises(PerformanceProviderError) as excinfo:
        Google(body=httpx.ConnectError("down")).provider().video_counters(AUTH, [VID])
    assert excinfo.value.code == PerformanceErrorCode.NETWORK_ERROR and excinfo.value.retryable
    with pytest.raises(PerformanceProviderError) as excinfo:
        Google(body=b"<html>oops</html>").provider().daily_metrics(AUTH, VID, START, END)
    assert excinfo.value.code == PerformanceErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("publish_code", "code"),
    [
        (PublishErrorCode.AUTHENTICATION_REQUIRED, "authentication_required"),
        (PublishErrorCode.NETWORK_ERROR, "network_error"),
    ],
)
def test_authorization_failures_are_normalized(publish_code, code):
    def refresh(token):
        raise PublishProviderError(publish_code)

    with pytest.raises(PerformanceProviderError) as excinfo:
        YouTubeMetricsProvider(refresh).authorize("1//0gToken")
    assert excinfo.value.code == code
    with pytest.raises(PerformanceProviderError):
        YouTubeMetricsProvider(lambda t: TOKEN).authorize("")


# --- the fake ----------------------------------------------------------------------------------


def fake(today=date(2026, 10, 22), **kw) -> FakeMetricsProvider:
    return FakeMetricsProvider(today=lambda: today, **kw)


def test_the_fake_is_deterministic_and_plausible():
    a, b = fake(), fake()
    for provider in (a, b):
        provider.register(VID, date(2026, 10, 10))
    first = a.daily_metrics(a.authorize("r"), VID, START, END)
    assert first == b.daily_metrics(b.authorize("r"), VID, START, END)
    assert first[0].day == date(2026, 10, 10)  # nothing before the video existed
    assert first[-1].day == date(2026, 10, 20)  # processed up to two days ago only
    for day in first:
        assert 0 <= day.engaged_views <= day.views and day.likes <= day.views
        assert day.average_view_percentage >= 0 and day.watch_time_seconds >= 0
    assert first[0].views > first[-1].views  # a decaying short-form curve


def test_the_fake_simulates_missing_videos_hidden_likes_and_failures():
    provider = fake()
    provider.register(VID, date(2026, 10, 1), hide_likes=True)
    auth = provider.authorize("r")
    counters = provider.video_counters(auth, [VID])[VID]
    assert counters.likes is None and counters.views > 0
    provider.delete(VID)
    assert provider.video_counters(auth, [VID]) == {}
    assert provider.daily_metrics(auth, VID, START, END) == []
    provider.fail("daily_metrics", [PerformanceErrorCode.QUOTA_EXCEEDED, None])
    with pytest.raises(PerformanceProviderError):
        provider.daily_metrics(auth, VID, START, END)
    provider.daily_metrics(auth, VID, START, END)  # the next call succeeds


def test_the_fake_labels_itself():
    assert fake().name == "fake" and YouTubeMetricsProvider(lambda t: t).name == "youtube"


# --- configuration -----------------------------------------------------------------------------


def settings_with(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


def test_the_factory_follows_configuration():
    assert isinstance(factory.get_performance_provider(settings_with(performance_provider="fake")),
                      FakeMetricsProvider)  # fmt: skip
    assert isinstance(
        factory.get_performance_provider(settings_with(performance_provider="youtube")),
        YouTubeMetricsProvider,
    )


def test_production_refuses_simulated_metrics():
    from app.core.config import production_problems

    production = Settings.model_construct(
        **{**get_settings().model_dump(), "app_env": "production", "performance_provider": "fake"}
    )
    assert "PERFORMANCE_PROVIDER must be youtube" in production_problems(production)
    with pytest.raises(RuntimeError):
        factory.get_performance_provider(production)


def test_analytics_needs_publishing():
    with pytest.raises(ValidationError) as excinfo:
        settings_with(youtube_analytics_enabled=True, youtube_publishing_enabled=False)
    assert "YOUTUBE_ANALYTICS_ENABLED needs YOUTUBE_PUBLISHING_ENABLED" in str(excinfo.value)
