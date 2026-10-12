import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def _public_error(error: dict[str, Any]) -> dict[str, Any]:
    """Keep what a client needs to show a message; drop the echoed input and context."""
    return {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}


def register_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def unexpected_error_to_json(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Must be registered before CORSMiddleware so this response still passes
        # through it: an exception that escapes to Starlette's outermost handler
        # gets no CORS headers, and browsers then report a network error instead
        # of a 500 the frontend can show.
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default 422 body includes `input`, which would send a rejected
        # password (or any other submitted value) back over the wire.
        return JSONResponse(
            status_code=422,
            content={"detail": [_public_error(error) for error in exc.errors()]},
        )
