"""Tiny real-broker smoke test: start a worker, round-trip `peaksift.ping`, check that the
background job tasks are registered, stop the worker.

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

EXPECTED_TASKS = (
    "peaksift.ping",
    "peaksift.transcribe_video",
    "peaksift.detect_clips",
    "peaksift.render_clip",
    "peaksift.render_clip_edit",
    "peaksift.analyze_reframe",
    "peaksift.generate_caption_track",
)


def _check_registered_tasks() -> int:
    """The live worker must know every job the API can enqueue, or jobs would be lost."""
    registered = celery_app.control.inspect(timeout=10).registered() or {}
    names = {task for tasks in registered.values() for task in tasks}
    missing = [task for task in EXPECTED_TASKS if task not in names]
    if missing:
        print(f"worker is missing tasks: {', '.join(missing)}", file=sys.stderr)
        return 1
    print("worker registered:", ", ".join(EXPECTED_TASKS))
    return 0


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
                return _check_registered_tasks()
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
