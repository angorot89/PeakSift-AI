"""Liveness never touches dependencies; readiness checks them within one deadline and
reveals only which component is unavailable."""

import time

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_storage
from app.cli import health as health_cli
from app.main import app
from app.services import health
from app.services.storage import LocalStorageProvider, StorageUnavailable

SECRET_HOST = "db.internal.example:5432"


@pytest.fixture
def storage(tmp_path):
    local = LocalStorageProvider(tmp_path / "media")
    app.dependency_overrides[get_storage] = lambda: local
    yield local
    app.dependency_overrides.pop(get_storage, None)


def broken(message: str = f"could not connect to {SECRET_HOST} password=hunter2"):
    def fail(*args, **kwargs):
        raise ConnectionError(message)

    return fail


def test_liveness_answers_without_touching_dependencies(client: TestClient, monkeypatch):
    monkeypatch.setattr(health, "check_database", broken())
    for path in ("/health", "/health/live"):
        response = client.get(path)
        assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_ready_when_database_redis_and_storage_answer(client: TestClient, storage, monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda settings: None)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok", "storage": "ok"},
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("component", ["database", "redis", "storage"])
def test_any_unavailable_dependency_makes_the_api_not_ready(
    component, client: TestClient, storage, monkeypatch
):
    monkeypatch.setattr(health, "check_redis", lambda settings: None)
    if component == "database":
        monkeypatch.setattr(health, "check_database", broken())
    elif component == "redis":
        monkeypatch.setattr(health, "check_redis", broken())
    else:
        monkeypatch.setattr(storage, "check", _raise(StorageUnavailable("bucket gone")))

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready" and body["checks"][component] == "unavailable"
    assert [n for n, r in body["checks"].items() if r != "ok"] == [component]
    assert SECRET_HOST not in response.text and "hunter2" not in response.text
    assert "bucket" not in response.text


def _raise(error):
    def fail(*args, **kwargs):
        raise error

    return fail


def test_a_hanging_dependency_fails_within_the_deadline():
    started = time.monotonic()
    results = health.run_checks(
        {"slow": lambda: time.sleep(3), "slower": lambda: time.sleep(3), "fast": lambda: None},
        deadline=0.5,
    )
    assert results == {"slow": "unavailable", "slower": "unavailable", "fast": "ok"}
    assert time.monotonic() - started < 1.5  # one shared deadline, not one per check


def test_the_real_database_check_passes_against_the_test_database():
    assert health.run_checks({"database": health.check_database}) == {"database": "ok"}


def test_worker_diagnostic_reports_names_only_and_exit_codes(monkeypatch, capsys, storage):
    monkeypatch.setattr(health, "check_redis", lambda settings: None)
    monkeypatch.setattr(health_cli, "media_storage", lambda settings: storage)
    monkeypatch.setattr(health, "check_tools", lambda settings: None)
    assert health_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "database: ok" in out and "scratch: ok" in out and "media_tools: ok" in out

    monkeypatch.setattr(health, "check_tools", broken("ffmpeg missing at /opt/secret/bin"))
    monkeypatch.setattr(health_cli, "ping_workers", lambda timeout: 0)
    assert health_cli.main(["--ping"]) == 1
    out = capsys.readouterr().out
    assert "media_tools: unavailable" in out and "workers: unavailable" in out
    assert "/opt/secret" not in out


def test_redis_check_fails_on_a_closed_port():
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"redis_url": "redis://127.0.0.1:9/0"})
    assert health.run_checks({"redis": lambda: health.check_redis(settings)}) == {
        "redis": "unavailable"
    }
