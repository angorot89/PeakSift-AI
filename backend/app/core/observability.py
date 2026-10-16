"""Logging: correlation ids, JSON in production, and secret redaction everywhere.

- **Request ids:** every HTTP request gets an id (a well-formed incoming ``X-Request-ID`` is
  kept, anything else replaced), returned in the ``X-Request-ID`` response header and
  attached to every log line written while the request is handled.
- **Job correlation:** a job enqueued during a request carries that request id to the
  worker (a task header); worker log lines carry it with the task name and the job's
  database id.
- **Format:** one JSON object per line in production (``LOG_FORMAT=json``), readable text
  otherwise.
- **Redaction:** every record — ours, uvicorn's, gunicorn's, Celery's, library logs and
  tracebacks — passes through :func:`redact` before it is written: API keys and OAuth
  tokens, ``Authorization``/cookie values, credentials in URLs, signed-URL and OAuth query
  parameters (``code``, ``state``, ``X-Amz-*``, ``upload_id``), JWTs, and local media and
  scratch paths (FFmpeg stderr tails name them).
"""

import contextvars
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
job_var: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("job", default=None)

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
REDACTED = "[redacted]"

_SECRET_PATTERNS = [
    # Provider credentials and tokens.
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}"),  # OpenAI
    re.compile(r"\bya29\.[A-Za-z0-9._-]+"),  # Google OAuth access token
    re.compile(r"\b1//[A-Za-z0-9._-]{10,}"),  # Google OAuth refresh token
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]+"),  # Google OAuth client secret
    re.compile(r"\b4/[0-9A-Za-z_-]{20,}"),  # Google OAuth authorization code
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
]
# key=value / key: value pairs whose value is secret (headers, query strings, dicts, reprs).
_SECRET_FIELDS = re.compile(
    r"(?i)(\b(?:[a-z0-9]+[_-])*(?:authorization|cookie|password|passwd|secret|api[_-]?key|"
    r"access[_-]?key(?:[_-]?id)?|secret[_-]?access[_-]?key|session[_-]?token|token|"
    r"upload[_-]?id|signature|x-amz-[a-z-]+)\b[\"']?\s*[=:]\s*[\"']?)([^\s\"'&,;}]+)"
)
# OAuth redirect parameters, only in query-string form ("status code: 500" stays readable).
_OAUTH_QUERY = re.compile(r"(?i)([?&](?:code|state)=)[^&\s\"']+")
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]*:[^/\s@]+@")


class Redactor:
    def __init__(self, path_roots: list[str] | None = None) -> None:
        candidates = [r for r in path_roots or [] if r]
        candidates += [os.path.realpath(r) for r in candidates]  # /var/… is /private/var/…
        roots = sorted({r.rstrip("/") for r in candidates if r.rstrip("/")}, key=len)
        self._paths = (
            re.compile("(?:" + "|".join(re.escape(r) for r in reversed(roots)) + r")/?[^\s'\"]*")
            if roots
            else None
        )

    def __call__(self, text: str) -> str:
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(REDACTED, text)
        text = _URL_CREDENTIALS.sub(rf"\1{REDACTED}@", text)
        text = _OAUTH_QUERY.sub(rf"\1{REDACTED}", text)
        text = _SECRET_FIELDS.sub(rf"\1{REDACTED}", text)
        if self._paths is not None:
            text = self._paths.sub("<path>", text)
        return text


redact = Redactor([tempfile.gettempdir()])


class RedactingFilter(logging.Filter):
    """Formats the record's message once, redacted, and attaches correlation ids."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — a malformed log call must not lose the line
            message = str(record.msg)
        record.msg, record.args = redact(message), None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        record.exc_info = None if record.exc_text else record.exc_info
        record.request_id = request_id_var.get()
        job = job_var.get() or {}
        record.task = job.get("task")
        record.job_id = job.get("job_id")
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "task", "job_id"):
            if value := getattr(record, field, None):
                entry[field] = value
        if record.exc_text:
            entry["exception"] = record.exc_text
        return json.dumps(entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s%(correlation)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        parts = [
            f"{key}={value}"
            for key in ("request_id", "task", "job_id")
            if (value := getattr(record, key, None))
        ]
        record.correlation = f" [{' '.join(parts)}]" if parts else ""
        return super().format(record)


_THIRD_PARTY = ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error", "gunicorn.access",
                "celery", "celery.task", "celery.worker")  # fmt: skip


def configure_logging(settings) -> None:
    """Install one redacting handler on the root logger and route server/worker loggers
    through it. Idempotent."""
    global redact
    from app.services.workspace import work_root

    redact = Redactor([str(settings.media_root.resolve()), str(work_root(settings)),
                       tempfile.gettempdir()])  # fmt: skip
    fmt = settings.log_format or ("json" if settings.is_production else "text")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(RedactingFilter())
    handler.set_name("peaksift")
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != "peaksift"] + [handler]
    root.setLevel(settings.log_level)
    for name in _THIRD_PARTY:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    # The query string can carry OAuth codes or signed-URL parameters; our access log line
    # (``app.access``) records the path without it, so uvicorn's own access log is muted.
    # HTTP client libraries log full request URLs at INFO; for us those include resumable
    # upload session URIs (bearer secrets). Redaction would catch them; keep them out anyway.
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("gunicorn.access").disabled = True


def new_request_id(incoming: str | None) -> str:
    return incoming if incoming and _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex


_access = logging.getLogger("app.access")


class RequestContextMiddleware:
    """Assigns the request id, returns it as ``X-Request-ID`` and writes one access line
    per request (method, path without the query string, status, duration)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id")
        request_id = new_request_id(incoming.decode("latin-1") if incoming else None)
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            path = scope.get("path", "")
            _access.log(
                logging.DEBUG if path.startswith("/health") else logging.INFO,
                "%s %s %s %.0fms",
                scope.get("method"),
                path,
                status,
                (time.perf_counter() - started) * 1000,
            )
            request_id_var.reset(token)
