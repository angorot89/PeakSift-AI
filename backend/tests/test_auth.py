import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import JWT_ALGORITHM
from app.models import User

EMAIL = "creator@example.com"
PASSWORD = "correct horse battery"

settings = get_settings()
COOKIE = settings.auth_cookie_name


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


# --- registration -----------------------------------------------------------


def test_register_creates_user_and_sets_cookie(client: TestClient):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert uuid.UUID(body["id"])
    assert body["created_at"]
    assert "password" not in body and "password_hash" not in body

    assert response.cookies.get(COOKIE)
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=" in set_cookie
    assert "secure" not in set_cookie  # APP_ENV=test; enabled in production


def test_register_normalizes_email(client: TestClient, db_session: Session):
    response = register(client, email="  Creator@Example.COM ")

    assert response.status_code == 201
    assert response.json()["email"] == EMAIL
    assert db_session.scalar(select(User).where(User.email == EMAIL)) is not None


def test_register_duplicate_email_conflicts(client: TestClient):
    assert register(client).status_code == 201

    response = register(client, email="CREATOR@example.com", password="another password")

    assert response.status_code == 409


def test_register_stores_argon2_hash_not_password(client: TestClient, db_session: Session):
    register(client)

    user = db_session.scalar(select(User).where(User.email == EMAIL))
    assert user is not None
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


def test_register_rejects_short_password(client: TestClient):
    assert register(client, password="short").status_code == 422


def test_register_rejects_invalid_email(client: TestClient):
    assert register(client, email="not-an-email").status_code == 422


def test_validation_errors_do_not_echo_submitted_values(client: TestClient):
    response = register(client, password="hunter2")

    assert response.status_code == 422
    assert "hunter2" not in response.text
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "password"]
    assert error["msg"]
    assert "input" not in error and "ctx" not in error


# --- login ------------------------------------------------------------------


def test_login_with_valid_credentials(client: TestClient):
    register(client)
    client.cookies.clear()

    response = login(client, email="Creator@Example.com")

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL
    assert "password_hash" not in response.json()
    assert response.cookies.get(COOKIE)


def test_login_with_wrong_password(client: TestClient):
    register(client)
    client.cookies.clear()

    response = login(client, password="wrong password")

    assert response.status_code == 401
    assert COOKIE not in response.cookies


def test_login_unknown_email_gives_same_response_as_wrong_password(client: TestClient):
    register(client)
    client.cookies.clear()

    wrong_password = login(client, password="wrong password")
    unknown_email = login(client, email="nobody@example.com")

    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json() == wrong_password.json()


# --- current user -----------------------------------------------------------


def test_me_when_authenticated(client: TestClient):
    registered = register(client).json()

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == registered


def test_me_when_unauthenticated(client: TestClient):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_rejects_expired_token(client: TestClient):
    user_id = register(client).json()["id"]
    now = datetime.now(UTC)
    expired = jwt.encode(
        {"sub": user_id, "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        settings.secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    client.cookies.set(COOKIE, expired)

    assert client.get("/auth/me").status_code == 401


def test_me_rejects_tampered_token(client: TestClient):
    token = register(client).cookies[COOKIE]
    client.cookies.set(COOKIE, token[:-2] + "xx")

    assert client.get("/auth/me").status_code == 401


def test_me_rejects_token_signed_with_other_key(client: TestClient):
    user_id = register(client).json()["id"]
    now = datetime.now(UTC)
    forged = jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + timedelta(hours=1)},
        "a-different-secret-key-with-enough-length-0123456789",
        algorithm=JWT_ALGORITHM,
    )
    client.cookies.set(COOKIE, forged)

    assert client.get("/auth/me").status_code == 401


def test_me_rejects_token_for_deleted_user(client: TestClient, db_session: Session):
    user_id = uuid.UUID(register(client).json()["id"])
    db_session.delete(db_session.get(User, user_id))
    db_session.commit()

    assert client.get("/auth/me").status_code == 401


# --- logout -----------------------------------------------------------------


def test_logout_clears_cookie(client: TestClient):
    register(client)
    assert client.get("/auth/me").status_code == 200

    response = client.post("/auth/logout")

    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"].lower()
    assert set_cookie.startswith(f"{COOKIE}=")
    assert "max-age=0" in set_cookie
    assert client.get("/auth/me").status_code == 401
