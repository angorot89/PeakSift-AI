"""Production refuses unsafe or incomplete configuration; development keeps easy defaults.
Host validation and trusted-proxy handling are applied by the app factory."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

SECRET = "pK3x9QzR7mVw2LtYb8NcJ4hF6sDgA1eU5oIqWr0ZyXv"


def production(**overrides) -> dict:
    values = {
        "app_env": "production",
        "secret_key": SECRET,
        "database_url": "postgresql+psycopg://app@db:5432/peaksift",
        "redis_url": "redis://redis:6379/0",
        "frontend_url": "https://app.peaksift.example",
        "allowed_hosts": "api.peaksift.example",
        "trusted_proxies": "10.0.0.0/8",
        "media_root": "/var/lib/peaksift/media",
        "celery_task_always_eager": False,  # the test suite's environment enables it
        "rate_limit_enabled": True,  # and disables this
        "semantic_provider": "clip_onnx",  # and uses the fake embedding provider
        "performance_provider": "youtube",  # and the fake metrics provider
    }
    values.update(overrides)
    return values


def test_a_complete_production_configuration_is_accepted():
    settings = Settings(**production())
    assert settings.is_production and settings.cookie_secure
    assert settings.allowed_host_list == ["api.peaksift.example"]


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"secret_key": "change-me-change-me-change-me-change-me"}, "SECRET_KEY"),
        ({"secret_key": "a" * 40}, "SECRET_KEY"),
        ({"frontend_url": "http://app.peaksift.example"}, "FRONTEND_URL"),
        ({"frontend_url": "https://*"}, "FRONTEND_URL"),
        ({"allowed_hosts": ""}, "ALLOWED_HOSTS is required"),
        ({"allowed_hosts": "*.peaksift.example"}, "wildcards"),
        ({"trusted_proxies": "*"}, "TRUSTED_PROXIES"),
        ({"trusted_proxies": "proxy.internal"}, "TRUSTED_PROXIES"),
        ({"celery_task_always_eager": True}, "CELERY_TASK_ALWAYS_EAGER"),
        ({"media_root": "./media"}, "MEDIA_ROOT"),
    ],
)
def test_unsafe_production_settings_fail_fast(overrides, problem):
    with pytest.raises(ValidationError) as excinfo:
        Settings(**production(**overrides))
    message = str(excinfo.value)
    assert problem in message
    assert SECRET not in message and "change-me" not in message  # names only, never values


@pytest.mark.parametrize("missing", ["redis_url", "media_root"])
def test_production_needs_explicit_infrastructure_settings(missing, monkeypatch):
    monkeypatch.delenv(missing.upper(), raising=False)
    values = production()
    values.pop(missing)
    with pytest.raises(ValidationError) as excinfo:
        Settings(**values)
    assert missing.upper() in str(excinfo.value)


def test_environment_variables_count_as_explicit(monkeypatch):
    for key, value in production().items():
        monkeypatch.setenv(key.upper(), str(value))
    assert Settings(_env_file=None).is_production


def test_unknown_environments_are_refused():
    with pytest.raises(ValidationError):
        Settings(**production(app_env="staging"))


def test_development_keeps_simple_defaults():
    settings = Settings(
        app_env="development", secret_key=SECRET, database_url="postgresql+psycopg://x@localhost/x"
    )
    assert settings.app_env == "development" and not settings.cookie_secure
    loose = Settings(
        app_env="development", secret_key=SECRET, database_url="postgresql+psycopg://x@localhost/x",
        allowed_hosts="", trusted_proxies="", frontend_url="http://localhost:3000",
    )  # fmt: skip
    assert loose.allowed_host_list == [] and loose.trusted_proxy_list == []  # fine outside prod


def test_production_app_validates_hosts_and_hides_docs():
    client = TestClient(
        create_app(Settings(**production())), base_url="http://api.peaksift.example"
    )
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
    evil = TestClient(create_app(Settings(**production())), base_url="http://evil.example")
    assert evil.get("/health").status_code == 400


def test_forwarded_headers_are_trusted_only_from_configured_proxies():
    app = create_app(Settings(**production(trusted_proxies="127.0.0.1")))

    @app.get("/whoami")
    def whoami(request: __import__("fastapi").Request) -> dict:
        return {"client": request.client.host, "scheme": request.url.scheme}

    headers = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}
    trusted = TestClient(app, base_url="http://api.peaksift.example", client=("127.0.0.1", 5000))
    assert trusted.get("/whoami", headers=headers).json() == {
        "client": "203.0.113.9",
        "scheme": "https",
    }
    untrusted = TestClient(
        app, base_url="http://api.peaksift.example", client=("198.51.100.7", 5000)
    )
    assert untrusted.get("/whoami", headers=headers).json() == {
        "client": "198.51.100.7",
        "scheme": "http",
    }


def test_a_rejected_configuration_never_echoes_any_value(monkeypatch):
    secret_url = "redis://:Sup3rSecretRedisPassw0rd@redis:6379/0"
    with pytest.raises(ValidationError) as excinfo:
        Settings(**production(redis_url=secret_url, secret_key="change-me" * 5))
    text = str(excinfo.value)
    assert "Sup3rSecret" not in text and "Passw0rd" not in text and "change-me" not in text
    assert "input_value" not in text


def test_empty_variables_mean_unset(monkeypatch):
    monkeypatch.setenv("PUBLISHING_TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    settings = Settings()
    assert settings.publishing_token_encryption_key is None
    assert settings.google_client_secret is None
