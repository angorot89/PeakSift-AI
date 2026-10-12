from fastapi.testclient import TestClient

from app.core.config import get_settings


def test_health_returns_ok(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_configured_frontend_origin(client: TestClient):
    origin = get_settings().frontend_url.rstrip("/")

    response = client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_unknown_origin(client: TestClient):
    response = client.get("/health", headers={"Origin": "https://example.com"})

    assert "access-control-allow-origin" not in response.headers
