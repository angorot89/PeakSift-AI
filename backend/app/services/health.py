"""Readiness checks for the API and workers.

Each check answers only "ok" or "unavailable": no hosts, ports, error text or credentials
ever leave this module (operators get the exception *type* in the log). Checks run
concurrently under one deadline, so a hanging dependency makes readiness fail fast
instead of hanging the probe. External providers (OpenAI, Google) are deliberately not
checked: their outages must not take the service out of a load balancer.
"""

import logging
import os
import shutil
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from sqlalchemy import text

from app.core.config import Settings
from app.services.storage import StorageProvider

logger = logging.getLogger(__name__)

DEADLINE_SECONDS = 5.0


def check_database() -> None:
    from app.core.database import engine

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def check_redis(settings: Settings) -> None:
    import redis

    client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        if not client.ping():
            raise ConnectionError("no PONG")
    finally:
        client.close()


def check_scratch(settings: Settings) -> None:
    from app.services.workspace import work_root

    root = work_root(settings)
    if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
        raise PermissionError("scratch is not writable")


def check_tools(settings: Settings) -> None:
    from app.services.clip_edit.composition import supports_captions

    for tool in (settings.ffmpeg_path, settings.ffprobe_path):
        if shutil.which(tool) is None:
            raise FileNotFoundError("a media tool is missing")
    if not supports_captions(settings.ffmpeg_path):
        raise RuntimeError("FFmpeg lacks libass (captions)")


def run_checks(checks: dict[str, Callable[[], None]], deadline: float = DEADLINE_SECONDS) -> dict:
    """``{name: "ok" | "unavailable"}`` for each check, all within ``deadline`` seconds."""
    results: dict[str, str] = {}
    pool = ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="health")
    try:
        futures = {name: pool.submit(check) for name, check in checks.items()}
        end = time.monotonic() + deadline  # one deadline for all checks together
        for name, future in futures.items():
            try:
                future.result(timeout=max(0.0, end - time.monotonic()))
                results[name] = "ok"
            except FutureTimeout:
                logger.warning("Readiness check %s timed out", name)
                results[name] = "unavailable"
            except Exception as error:  # noqa: BLE001 — any failure means "not ready"
                logger.warning("Readiness check %s failed: %s", name, type(error).__name__)
                results[name] = "unavailable"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # never wait on a hung dependency
    return results


def api_checks(settings: Settings, storage: StorageProvider) -> dict[str, Callable[[], None]]:
    return {
        "database": check_database,
        "redis": lambda: check_redis(settings),
        "storage": storage.check,
    }


def worker_checks(settings: Settings, storage: StorageProvider) -> dict[str, Callable[[], None]]:
    return {
        **api_checks(settings, storage),
        "scratch": lambda: check_scratch(settings),
        "media_tools": lambda: check_tools(settings),
    }
