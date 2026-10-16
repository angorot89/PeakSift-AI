"""Request ids, job correlation, JSON logs and secret redaction."""

import io
import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.core import observability
from app.core.config import Settings, get_settings
from app.core.observability import (
    JsonFormatter,
    RedactingFilter,
    Redactor,
    configure_logging,
    job_var,
    request_id_var,
)
from app.services import health
from app.workers import celery_app as worker

SECRETS = {
    "openai": "sk-proj-abcdefghijklmnopqrstuvwx",
    "google access": "ya29.a0AfH6SMBxyz-123",
    "google refresh": "1//0gAbcdefghijklmnop",
    "google client secret": "GOCSPX-abcDEF123",
    "oauth code": "4/0AX4XfWjabcdefghijklmnopqrstuv",
    "aws key id": "AKIAABCDEFGHIJKLMNOP",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abcdefghijk",
}


@pytest.mark.parametrize("name", SECRETS)
def test_known_credential_shapes_are_redacted(name):
    secret = SECRETS[name]
    assert secret not in Redactor()(f"something happened with {secret} here")


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("{'aws_secret_access_key': 'wJalrXUtnFEMI/K7MDENG'}", "wJalrXUtnFEMI"),
        ("S3_SECRET_ACCESS_KEY=supersecret", "supersecret"),
        ("postgresql+psycopg://app:hunter2@db:5432/peaksift", "hunter2"),
        ("redis://:redispw@redis:6379/0", "redispw"),
        ("GET /youtube/callback?code=abc-oauth-code&state=Zm9vYmFy", "abc-oauth-code"),
        ("GET /youtube/callback?code=abc-oauth-code&state=Zm9vYmFy", "Zm9vYmFy"),
        ("?X-Amz-Credential=AKIAX%2F2026&X-Amz-Signature=abcdef0123", "abcdef0123"),
        ("videos?uploadType=resumable&upload_id=ADPycdtS3cr3t", "ADPycdtS3cr3t"),
        ("Authorization: Bearer opaque-token-value", "opaque-token-value"),
        ("Cookie: peaksift_access_token=session-cookie-value", "session-cookie-value"),
        ("client_secret=abc123 password: pw456", "abc123"),
        ("client_secret=abc123 password: pw456", "pw456"),
    ],
)
def test_secret_fields_urls_and_query_parameters_are_redacted(text, leaked):
    assert leaked not in Redactor()(text)


def test_local_media_and_scratch_paths_are_hidden():
    redact = Redactor(["/var/lib/peaksift/media", "/var/lib/peaksift/work"])
    line = redact("ffmpeg: /var/lib/peaksift/work/edits/3f/work-1/short.mp4: Invalid data")
    assert "/var/lib" not in line and "<path>" in line


def test_symlinked_temp_roots_are_hidden_whole(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "alias").symlink_to(real)
    redact = Redactor([str(tmp_path / "alias")])
    assert redact(f"open {real}/edits/x.mp4: failed") == "open <path> failed"
    assert redact(f"open {tmp_path}/alias/x.mp4 now") == "open <path> now"


def test_ordinary_operational_text_survives():
    text = "GET /projects/3f2c 200 12ms; status code: 500; max_tokens=4000; exit code 1"
    assert Redactor(["/var/lib/peaksift"])(text) == text


def capture(level=logging.INFO) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger(f"test.observability.{id(stream)}")
    logger.handlers, logger.propagate, logger.level = [handler], False, level
    return logger, stream


def lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_lines_carry_correlation_and_redacted_tracebacks():
    logger, stream = capture()
    request_token = request_id_var.set("req-0123456789")
    job_token = job_var.set({"task": "peaksift.render_clip", "job_id": "abc"})
    try:
        try:
            raise RuntimeError(f"upload failed with {SECRETS['google refresh']}")
        except RuntimeError:
            logger.exception("Publishing %s failed using %s", "job", SECRETS["openai"])
    finally:
        job_var.reset(job_token)
        request_id_var.reset(request_token)

    [entry] = lines(stream)
    assert entry["level"] == "ERROR" and entry["request_id"] == "req-0123456789"
    assert entry["task"] == "peaksift.render_clip" and entry["job_id"] == "abc"
    assert "RuntimeError" in entry["exception"]
    raw = stream.getvalue()
    assert SECRETS["openai"] not in raw and SECRETS["google refresh"] not in raw


def test_every_response_carries_a_request_id(client: TestClient):
    generated = client.get("/health").headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert client.get("/health").headers["x-request-id"] != generated
    assert client.get("/no-such-route").headers["x-request-id"]


@pytest.mark.parametrize(
    ("incoming", "kept"),
    [
        ("lb-req-12345678", True),
        ("short", False),
        ("has space here", False),
        ("x" * 65, False),
        ("ok\r\nX-Injected: 1", False),
    ],  # fmt: skip
)
def test_incoming_request_ids_are_kept_only_when_well_formed(client: TestClient, incoming, kept):
    try:
        response = client.get("/health", headers={"X-Request-ID": incoming})
    except Exception:  # the HTTP client itself refuses a header with CR/LF
        assert not kept
        return
    assert (response.headers["x-request-id"] == incoming) is kept


def test_request_logs_share_the_request_id_and_drop_the_query_string(
    client: TestClient, monkeypatch
):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    monkeypatch.setattr(health, "check_redis", lambda settings: (_ for _ in ()).throw(OSError()))
    try:
        ready = client.get("/health/ready")
        listed = client.get("/projects?code=oauth-secret-code&state=s")  # 401, but logged
    finally:
        root.removeHandler(handler)

    entries = lines(stream)
    ready_id, listed_id = ready.headers["x-request-id"], listed.headers["x-request-id"]
    assert any(
        e["logger"] == "app.services.health" and e.get("request_id") == ready_id for e in entries
    )
    access = [
        e for e in entries if e["logger"] == "app.access" and e.get("request_id") == listed_id
    ]
    assert [e["message"].rsplit(" ", 1)[0] for e in access] == ["GET /projects 401"]
    assert "oauth-secret-code" not in stream.getvalue()


class FakeTask:
    name = "peaksift.render_clip_edit"

    def __init__(self, headers: dict) -> None:
        self.request = headers


def test_jobs_carry_the_request_id_from_api_to_worker():
    headers: dict = {}
    token = request_id_var.set("req-from-api-1234")
    try:
        worker._carry_request_id(headers=headers)
    finally:
        request_id_var.reset(token)
    assert headers == {worker.REQUEST_ID_HEADER: "req-from-api-1234"}

    worker._enter_job(task_id="t-1", task=FakeTask(headers), args=["edit-uuid"])
    assert request_id_var.get() == "req-from-api-1234"
    assert job_var.get() == {"task": "peaksift.render_clip_edit", "job_id": "edit-uuid"}
    worker._leave_job(task_id="t-1")
    assert request_id_var.get() is None and job_var.get() is None


def test_an_eager_job_inherits_the_surrounding_request_id():
    token = request_id_var.set("req-surrounding-1")
    try:
        worker._enter_job(task_id="t-2", task=FakeTask({}), args=["x"])
        assert request_id_var.get() == "req-surrounding-1"
        worker._leave_job(task_id="t-2")
        assert request_id_var.get() == "req-surrounding-1" and job_var.get() is None
    finally:
        request_id_var.reset(token)


def test_production_logs_json_and_development_logs_text():
    base = get_settings().model_dump()
    try:
        configure_logging(Settings.model_construct(**{**base, "app_env": "production"}))
        [ours] = [h for h in logging.getLogger().handlers if h.get_name() == "peaksift"]
        assert isinstance(ours.formatter, JsonFormatter)
        assert logging.getLogger("uvicorn.access").disabled  # its lines include query strings
        configure_logging(Settings.model_construct(**{**base, "log_format": "text"}))
        [ours] = [h for h in logging.getLogger().handlers if h.get_name() == "peaksift"]
        assert isinstance(ours.formatter, observability.TextFormatter)
    finally:
        configure_logging(get_settings())
