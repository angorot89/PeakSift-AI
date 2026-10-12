"""Tiny real-broker smoke test: start a worker, round-trip `peaksift.ping`, stop the worker.

Used by CI (against the Redis service) and by the acceptance checklist. It proves that the
broker, the worker process and task registration work together; it transcribes nothing.

    python scripts/celery_smoke.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "0")

from app.workers.celery_app import celery_app  # noqa: E402
from app.workers.transcription_tasks import ping  # noqa: E402


def main() -> int:
    with celery_app.connection_for_write() as connection:
        connection.ensure_connection(max_retries=2)
    print("broker reachable:", celery_app.conf.broker_url.split("@")[-1])

    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.workers.celery_app",
            "worker",
            "--loglevel=warning",
            "--pool=solo",
            "--concurrency=1",
            "--without-gossip",
            "--without-mingle",
        ],
        env={**os.environ, "CELERY_TASK_ALWAYS_EAGER": "0"},
    )
    try:
        deadline = time.time() + 60
        result = None
        while time.time() < deadline:
            # The result is only consulted for this smoke test; application state never
            # depends on the result backend.
            result = ping.apply_async()
            try:
                value = result.get(timeout=5)
            except Exception:
                continue
            if value == "pong":
                print("worker round-trip: pong")
                return 0
        print("worker did not answer within 60s", file=sys.stderr)
        return 1
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()


if __name__ == "__main__":
    sys.exit(main())
