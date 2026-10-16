"""Every API response carries strict security headers; media keeps its own caching."""

import io
import uuid

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_production_config import production

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
    "cross-origin-resource-policy": "same-site",
}


def test_json_errors_and_unknown_routes_all_carry_the_headers(client: TestClient):
    for response in (client.get("/health"), client.get("/projects"), client.get("/nope")):
        for name, value in EXPECTED.items():
            assert response.headers[name] == value, (response.url, name)
        assert response.headers["cache-control"] == "no-store"
        assert "strict-transport-security" not in response.headers  # development: no HSTS


def test_media_keeps_its_own_cache_policy(client: TestClient):
    client.post("/auth/register", json={"email": f"h{uuid.uuid4().hex[:6]}@example.com",
                                        "password": "correct horse battery"})  # fmt: skip
    project = client.post("/projects", json={"name": "H"}).json()["id"]
    video = client.post(
        f"/projects/{project}/videos", files={"file": ("v.mp4", b"x" * 2048, "video/mp4")}
    ).json()
    response = client.get(f"/videos/{video['id']}/content", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert response.headers["cache-control"] == "private, no-store"  # not duplicated
    assert response.headers.get_list("cache-control") == ["private, no-store"]
    assert response.headers["x-frame-options"] == "DENY"


def test_production_adds_hsts():
    from app.core.config import Settings

    settings = Settings(**production())
    with TestClient(create_app(settings), base_url="https://api.peaksift.example") as client:
        response = client.get("/health")
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_headers_never_break_streaming_bodies(client: TestClient):
    response = client.get("/health/live")
    assert response.json() == {"status": "ok"} and io.BytesIO(response.content).read()
