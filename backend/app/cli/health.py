"""Worker (and API host) diagnostics, usable as a container healthcheck.

    python -m app.cli.health            # this host can do the work: exit 0, else 1
    python -m app.cli.health --ping     # also ask running workers to answer over the broker

Checks PostgreSQL, Redis, media storage, the scratch directory and the media tools (FFmpeg
and ffprobe, with libass for captions). Prints one ``name: ok|unavailable`` line per check —
never hosts, errors or credentials.
"""

import argparse
import sys

from app.core.config import get_settings
from app.services.health import run_checks, worker_checks
from app.services.storage import media_storage


def ping_workers(timeout: float) -> int:
    from app.workers.celery_app import celery_app

    return len(celery_app.control.ping(timeout=timeout) or [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.health", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--ping", action="store_true", help="require at least one live worker")
    parser.add_argument("--ping-timeout", type=float, default=3.0)
    args = parser.parse_args(argv)

    settings = get_settings()
    results = run_checks(worker_checks(settings, media_storage(settings)), deadline=10)
    if args.ping:
        try:
            workers = ping_workers(args.ping_timeout)
        except Exception:  # noqa: BLE001 — the broker is unreachable
            workers = 0
        results["workers"] = "ok" if workers else "unavailable"
        print(f"workers answering: {workers}")
    for name, result in results.items():
        print(f"{name}: {result}")
    return 0 if all(result == "ok" for result in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
