"""Liveness and readiness.

- ``GET /health/live`` (and the original ``GET /health``): the process is serving requests.
  No dependency is touched, so a database outage never restarts healthy API processes.
- ``GET /health/ready``: the API can do real work — PostgreSQL, Redis (the job broker and
  rate limiter) and media storage all answer within a short deadline. ``503`` otherwise,
  naming only which component is unavailable (never hosts, errors or credentials).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import Storage
from app.core.config import get_settings
from app.services.health import api_checks, run_checks

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/health/live")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(storage: Storage) -> JSONResponse:
    checks = run_checks(api_checks(get_settings(), storage))
    is_ready = all(result == "ok" for result in checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
        headers={"Cache-Control": "no-store"},
    )
