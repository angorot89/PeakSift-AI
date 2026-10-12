from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

crash_router = APIRouter()


@crash_router.get("/__test_crash")
def crash() -> None:
    raise RuntimeError("secret internal detail /Users/someone/media")


app.include_router(crash_router)


def test_unhandled_exception_becomes_generic_500_with_cors(client: TestClient):
    origin = get_settings().frontend_url.rstrip("/")

    response = client.get("/__test_crash", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "secret internal detail" not in response.text
    assert "/Users/" not in response.text
    # The browser can read the error only if CORS headers are present.
    assert response.headers["access-control-allow-origin"] == origin


def test_unhandled_exception_without_origin(client: TestClient):
    response = client.get("/__test_crash")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
