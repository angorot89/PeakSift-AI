from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _public_error(error: dict[str, Any]) -> dict[str, Any]:
    """Keep what a client needs to show a message; drop the echoed input and context."""
    return {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default 422 body includes `input`, which would send a rejected
        # password (or any other submitted value) back over the wire.
        return JSONResponse(
            status_code=422,
            content={"detail": [_public_error(error) for error in exc.errors()]},
        )
