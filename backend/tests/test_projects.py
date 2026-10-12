import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Project

PASSWORD = "correct horse battery"


def sign_up(client: TestClient, email: str) -> dict:
    """Register (which also logs in) and return the user payload."""
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return response.json()


def create_project(client: TestClient, name: str) -> dict:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


# --- authentication ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/projects"),
        ("post", "/projects"),
        ("get", f"/projects/{uuid.uuid4()}"),
    ],
)
def test_project_endpoints_require_authentication(client: TestClient, method: str, path: str):
    response = client.request(method, path, json={"name": "x"})

    assert response.status_code == 401


# --- create -----------------------------------------------------------------


def test_create_project(client: TestClient, db_session: Session):
    user = sign_up(client, "owner@example.com")

    body = create_project(client, "Kai Cenat Stream — September 28")

    assert body["name"] == "Kai Cenat Stream — September 28"
    assert body["status"] == "created"
    assert uuid.UUID(body["id"])
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(body["updated_at"]).tzinfo is not None
    assert "user_id" not in body

    stored = db_session.get(Project, uuid.UUID(body["id"]))
    assert stored is not None
    assert str(stored.user_id) == user["id"]


def test_create_project_strips_whitespace(client: TestClient):
    sign_up(client, "owner@example.com")

    body = create_project(client, "   Podcast ep. 12   ")

    assert body["name"] == "Podcast ep. 12"


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_create_project_rejects_invalid_names(client: TestClient, name: str):
    sign_up(client, "owner@example.com")

    response = client.post("/projects", json={"name": name})

    assert response.status_code == 422


def test_create_project_requires_name(client: TestClient):
    sign_up(client, "owner@example.com")

    assert client.post("/projects", json={}).status_code == 422


# --- list -------------------------------------------------------------------


def test_list_projects_returns_own_projects_newest_first(client: TestClient, db_session: Session):
    sign_up(client, "owner@example.com")
    older = create_project(client, "Older")
    create_project(client, "Newer")
    # Every test runs in one transaction, where `now()` is constant; back-date explicitly.
    db_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(older["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(days=1))
    )
    db_session.commit()
    db_session.expire_all()

    response = client.get("/projects")

    assert response.status_code == 200
    assert [p["name"] for p in response.json()] == ["Newer", "Older"]


def test_list_projects_is_empty_for_new_user(client: TestClient):
    sign_up(client, "owner@example.com")

    assert client.get("/projects").json() == []


def test_list_projects_excludes_other_users_projects(client: TestClient):
    sign_up(client, "alice@example.com")
    create_project(client, "Alice's project")
    client.cookies.clear()

    sign_up(client, "bob@example.com")
    create_project(client, "Bob's project")

    names = [p["name"] for p in client.get("/projects").json()]
    assert names == ["Bob's project"]


# --- detail -----------------------------------------------------------------


def test_get_own_project(client: TestClient):
    sign_up(client, "owner@example.com")
    created = create_project(client, "Detail")

    response = client.get(f"/projects/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_other_users_project_is_not_found(client: TestClient):
    sign_up(client, "alice@example.com")
    alices = create_project(client, "Alice's project")
    client.cookies.clear()

    sign_up(client, "bob@example.com")
    response = client.get(f"/projects/{alices['id']}")

    assert response.status_code == 404


def test_get_missing_project_is_not_found(client: TestClient):
    sign_up(client, "owner@example.com")

    assert client.get(f"/projects/{uuid.uuid4()}").status_code == 404


def test_get_project_with_malformed_id_is_rejected(client: TestClient):
    sign_up(client, "owner@example.com")

    assert client.get("/projects/not-a-uuid").status_code == 422
