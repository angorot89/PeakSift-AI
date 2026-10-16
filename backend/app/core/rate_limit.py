"""Redis-backed rate limits.

Fixed windows: ``INCR`` a counter named by the limit, the subject and the window, and refuse
with ``429`` plus ``Retry-After`` once the window's budget is spent. Anonymous endpoints
(register, login) are limited per client IP — the address ``ProxyHeadersMiddleware``
derived from trusted proxies only — and login additionally per account, so spreading
guesses over many addresses does not help. Expensive operations (uploads, transcription,
detection, renders, framing, word timing, retries of each) are limited per user.

Redis is a hard dependency here: if it cannot be reached, a limited endpoint answers 503
rather than running unlimited (readiness reports the same outage). Every budget is server
configuration: the defaults below, overridable with ``RATE_LIMITS``.
"""

import hashlib
import logging
import math
import time
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limit:
    count: int
    seconds: int


HOUR = 3600
DEFAULT_LIMITS: dict[str, Limit] = {
    "login_ip": Limit(20, 60),
    "login_account": Limit(10, 15 * 60),
    "register_ip": Limit(10, HOUR),
    "video_upload": Limit(30, HOUR),
    "audio_upload": Limit(100, HOUR),
    "transcription": Limit(30, HOUR),
    "clip_detection": Limit(30, HOUR),
    "clip_render": Limit(200, HOUR),
    "edit_render": Limit(200, HOUR),
    "reframe": Limit(100, HOUR),
    "caption_timing": Limit(100, HOUR),
    "oauth_start": Limit(10, HOUR),
}


def parse_overrides(text: str) -> dict[str, Limit]:
    """``"login_ip=5/60,edit_render=50/3600"`` → limits. Unknown names or bad values raise."""
    limits: dict[str, Limit] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        name, _, spec = item.partition("=")
        count, _, seconds = spec.partition("/")
        if name.strip() not in DEFAULT_LIMITS or not count.isdigit() or not seconds.isdigit():
            raise ValueError("RATE_LIMITS entries must be <known name>=<count>/<seconds>")
        if int(count) < 1 or int(seconds) < 1:
            raise ValueError("RATE_LIMITS counts and windows must be positive")
        limits[name.strip()] = Limit(int(count), int(seconds))
    return limits


class Counter(Protocol):
    def hit(self, key: str, window_seconds: int) -> int: ...


class RedisCounter:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)

    def hit(self, key: str, window_seconds: int) -> int:
        pipeline = self._client.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, window_seconds + 1, nx=True)
        count, _ = pipeline.execute()
        return int(count)


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


class LimiterUnavailable(Exception):
    """The counter store could not be reached."""


class RateLimiter:
    def __init__(self, counter: Counter, limits: dict[str, Limit], *, clock=time.time) -> None:
        self.counter, self.limits, self.clock = counter, limits, clock

    def check(self, name: str, subject: str) -> None:
        limit = self.limits[name]
        now = self.clock()
        window = int(now // limit.seconds)
        # Subjects are hashed: no email addresses or IPs are written to Redis in clear.
        digest = hashlib.sha256(subject.encode()).hexdigest()[:32]
        try:
            count = self.counter.hit(f"rl:{name}:{digest}:{window}", limit.seconds)
        except Exception as error:  # noqa: BLE001 — any store failure
            logger.error("Rate limiter unavailable: %s", type(error).__name__)
            raise LimiterUnavailable() from None
        if count > limit.count:
            raise RateLimited(max(1, math.ceil((window + 1) * limit.seconds - now)))


_limiter: tuple[Settings, RateLimiter] | None = None


def get_limiter() -> RateLimiter | None:
    """The configured limiter, or None when rate limiting is switched off (tests only)."""
    global _limiter
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return None
    if _limiter is None or _limiter[0] is not settings:
        limits = {**DEFAULT_LIMITS, **parse_overrides(settings.rate_limits)}
        _limiter = (settings, RateLimiter(RedisCounter(settings.redis_url), limits))
    return _limiter[1]


def enforce(name: str, subject: str) -> None:
    """Count one use of ``name`` by ``subject``; 429 or 503 instead of proceeding."""
    limiter = get_limiter()
    if limiter is None:
        return
    try:
        limiter.check(name, subject)
    except RateLimited as limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Try again in {_wait(limited.retry_after)}.",
            headers={"Retry-After": str(limited.retry_after)},
        ) from None
    except LimiterUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The service is temporarily unavailable. Please try again shortly.",
        ) from None


def _wait(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} minutes"


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def per_ip(name: str):
    """A dependency limiting ``name`` per client address."""

    def dependency(request: Request) -> None:
        enforce(name, client_address(request))

    return Depends(dependency)


def per_user(name: str):
    """A dependency limiting ``name`` per signed-in user (after authentication)."""
    from app.api.deps import CurrentUser

    def dependency(user: CurrentUser) -> None:
        enforce(name, str(user.id))

    return Depends(dependency)
