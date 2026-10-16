"""Rate limits: per address for anonymous endpoints, per user for expensive operations,
429 with Retry-After, fail closed without Redis, budgets as server configuration."""

import os

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import rate_limit
from app.core.config import Settings, get_settings
from app.core.rate_limit import DEFAULT_LIMITS, Limit, RateLimited, RateLimiter, parse_overrides

PASSWORD = "correct horse battery"


class MemoryCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def hit(self, key: str, window_seconds: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class BrokenCounter:
    def hit(self, key: str, window_seconds: int) -> int:
        raise ConnectionError("redis://:secret@redis:6379 unreachable")


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def limiter(monkeypatch):
    """The application's limiter, on an in-memory counter, with small budgets."""
    limits = {**DEFAULT_LIMITS, "login_ip": Limit(3, 60), "login_account": Limit(2, 900),
              "register_ip": Limit(2, 3600), "video_upload": Limit(2, 3600),
              "edit_render": Limit(2, 3600)}  # fmt: skip
    instance = RateLimiter(MemoryCounter(), limits, clock=Clock())
    monkeypatch.setattr(rate_limit, "get_limiter", lambda: instance)
    return instance


def register(client: TestClient, email: str):
    return client.post("/auth/register", json={"email": email, "password": PASSWORD})


def login(client: TestClient, email: str, password: str = PASSWORD, ip: str | None = None):
    return client.post("/auth/login", json={"email": email, "password": password})


# --- the limiter itself -----


def test_a_budget_is_spent_then_refused_until_the_window_ends():
    clock = Clock(1_000_050.0)  # 30 s into a 60 s window (windows start at multiples of 60)
    limiter = RateLimiter(MemoryCounter(), {"login_ip": Limit(2, 60)}, clock=clock)
    limiter.check("login_ip", "10.0.0.1")
    limiter.check("login_ip", "10.0.0.1")
    with pytest.raises(RateLimited) as refused:
        limiter.check("login_ip", "10.0.0.1")
    assert refused.value.retry_after == 30
    limiter.check("login_ip", "10.0.0.2")  # another subject has its own budget
    clock.now += 30
    limiter.check("login_ip", "10.0.0.1")  # a new window


def test_subjects_are_hashed_before_they_reach_the_store():
    counter = MemoryCounter()
    RateLimiter(counter, {"login_account": Limit(5, 60)}).check("login_account", "a@example.com")
    [key] = counter.counts
    assert "a@example.com" not in key and key.startswith("rl:login_account:")


@pytest.mark.parametrize(
    "text", ["nope=1/60", "login_ip=0/60", "login_ip=5/0", "login_ip=five/60", "login_ip"]
)
def test_overrides_are_validated(text):
    with pytest.raises(ValueError):
        parse_overrides(text)
    with pytest.raises(ValidationError) as excinfo:
        Settings(**{**get_settings().model_dump(), "rate_limits": text})
    assert "RATE_LIMITS" in str(excinfo.value)


def test_overrides_replace_individual_budgets():
    assert parse_overrides("login_ip=5/60, edit_render=50/3600") == {
        "login_ip": Limit(5, 60),
        "edit_render": Limit(50, 3600),
    }


def test_production_refuses_to_run_without_rate_limits():
    from app.core.config import production_problems

    settings = Settings.model_construct(
        **{**get_settings().model_dump(), "rate_limit_enabled": False}
    )
    assert "RATE_LIMIT_ENABLED must be on" in production_problems(settings)


# --- anonymous endpoints, per address -----


def test_login_attempts_are_limited_per_address(client: TestClient, limiter):
    for attempt in range(3):
        assert login(client, f"nobody{attempt}@example.com").status_code == 401
    refused = login(client, "nobody9@example.com")
    assert refused.status_code == 429
    assert refused.headers["retry-after"].isdigit()
    assert refused.json()["detail"].startswith("Too many requests. Try again in")


def test_login_is_limited_per_account_across_addresses(client: TestClient, limiter):
    limiter.limits["login_ip"] = Limit(100, 60)
    assert register(client, "target@example.com").status_code == 201
    client.cookies.clear()
    assert login(client, "target@example.com", "wrong-password-1").status_code == 401
    assert login(client, "Target@Example.com", "wrong-password-2").status_code == 401
    # Even the right password waits: the account's budget is spent, whoever is guessing.
    assert login(client, "target@example.com").status_code == 429


def test_registration_is_limited_per_address(client: TestClient, limiter):
    assert register(client, "one@example.com").status_code == 201
    assert register(client, "two@example.com").status_code == 201
    assert register(client, "three@example.com").status_code == 429


def test_the_address_comes_from_trusted_proxies_only(limiter):
    from app.main import create_app

    def attempt(client: TestClient, n: int, forwarded: str):
        body = {"email": f"x{n}@example.com", "password": "pw-123456"}
        return client.post("/auth/login", headers={"X-Forwarded-For": forwarded}, json=body)

    settings = get_settings().model_copy(update={"trusted_proxies": "127.0.0.1/32"})
    with TestClient(create_app(settings), client=("127.0.0.1", 5000)) as proxied:
        # Four different real clients behind the trusted proxy: each has its own budget.
        assert all(attempt(proxied, n, f"203.0.113.{n}").status_code == 401 for n in range(4))
    with TestClient(create_app(get_settings()), client=("198.51.100.7", 5000)) as direct:
        for n in range(3):
            attempt(direct, 10 + n, f"203.0.113.{10 + n}")
        # An untrusted peer cannot rotate its identity with forged forwarding headers.
        assert attempt(direct, 99, "203.0.113.99").status_code == 429


# --- expensive operations, per user -----


def test_uploads_are_limited_per_user(client: TestClient, limiter):
    assert register(client, "uploader@example.com").status_code == 201
    project = client.post("/projects", json={"name": "P"}).json()["id"]
    url = f"/projects/{project}/videos"
    files = {"file": ("v.mp4", b"not a real video", "video/mp4")}
    assert client.post(url, files=files).status_code == 201
    assert client.post(url, files=files).status_code == 201
    refused = client.post(url, files=files)
    assert refused.status_code == 429 and "retry-after" in refused.headers

    client.cookies.clear()
    assert register(client, "other-uploader@example.com").status_code == 201
    other = client.post("/projects", json={"name": "P"}).json()["id"]
    assert client.post(f"/projects/{other}/videos", files=files).status_code == 201


def test_limits_apply_only_after_authentication(client: TestClient, limiter):
    url = "/projects/00000000-0000-4000-8000-000000000000/videos"
    for _ in range(5):
        assert client.post(url, files={"file": ("v.mp4", b"x", "video/mp4")}).status_code == 401


def test_every_expensive_start_and_retry_is_limited():
    expected = {
        ("POST", "/projects/{project_id}/videos"): "video_upload",
        ("POST", "/projects/{project_id}/audio-assets"): "audio_upload",
        ("POST", "/projects/{project_id}/videos/{video_id}/transcription"): "transcription",
        ("POST", "/projects/{project_id}/videos/{video_id}/transcription/retry"): "transcription",
        ("POST", "/projects/{project_id}/videos/{video_id}/clip-detection"): "clip_detection",
        ("POST", "/projects/{project_id}/videos/{video_id}/clip-detection/{run_id}/retry"):
            "clip_detection",
    }  # fmt: skip
    from app.main import ROUTERS

    limited: dict[tuple[str, str], list[str]] = {}
    for router in ROUTERS:
        for route in router.routes:
            names = [d.dependency.__qualname__ for d in getattr(route, "dependencies", [])]
            if any(n.startswith(("per_user.", "per_ip.")) for n in names):
                for method in route.methods:
                    limited.setdefault((method, route.path), []).extend(names)
    for key in expected:
        assert key in limited, key
    starts = [path for (method, path) in limited if method == "POST"]
    fragments = ("/clip", "/clip/retry", "/edits", "/edits/{edit_id}/retry", "/reframe",
                 "/reframe/{analysis_id}/retry", "/caption-tracks",
                 "/caption-tracks/{track_id}/retry", "/auth/login", "/auth/register")  # fmt: skip
    for fragment in fragments:
        assert any(path.endswith(fragment) for path in starts), fragment


# --- Redis unavailable -----


def test_without_the_store_limited_endpoints_fail_closed(client: TestClient, monkeypatch):
    broken = RateLimiter(BrokenCounter(), DEFAULT_LIMITS)
    monkeypatch.setattr(rate_limit, "get_limiter", lambda: broken)
    response = login(client, "someone@example.com")
    assert response.status_code == 503
    assert "secret" not in response.text and "redis" not in response.text.lower()


def _redis_available() -> bool:
    try:
        rate_limit.RedisCounter(get_settings().redis_url)._client.ping()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(
    not os.environ.get("REQUIRE_REDIS") and not _redis_available(), reason="needs a local Redis"
)
def test_the_real_redis_counter_counts_and_expires():
    import uuid

    counter = rate_limit.RedisCounter(get_settings().redis_url)
    key = f"rl:test:{uuid.uuid4().hex}:0"
    assert [counter.hit(key, 2) for _ in range(3)] == [1, 2, 3]
    ttl = counter._client.ttl(key)
    assert 0 < ttl <= 3
    counter._client.delete(key)
