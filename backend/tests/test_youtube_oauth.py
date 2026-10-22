"""Connecting YouTube: least-privilege scope, PKCE, single-use user-bound state, fixed
redirects, encrypted refresh tokens that never reach the browser. No network: the token
exchange is replaced at ``_fetch_token``."""

import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api import publishing as api
from app.core.config import Settings, get_settings
from app.models import OAuthState, PublishingConnection
from app.services.publishing import youtube_oauth as oauth
from app.services.publishing.tokens import EncryptedToken, TokenCipher, generate_key

PASSWORD = "correct horse battery"
CLIENT_ID = "1234-test.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-test-client-secret"
REDIRECT = "http://localhost:8000/publishing/youtube/callback"
REFRESH = "1//0gTestRefreshTokenValue"
ACCESS = "ya29.TestAccessTokenValue"


def enabled_settings(**overrides) -> Settings:
    return Settings(
        **{
            **get_settings().model_dump(),
            "youtube_publishing_enabled": True,
            "publishing_token_encryption_key": generate_key(),
            "google_client_id": CLIENT_ID,
            "google_client_secret": CLIENT_SECRET,
            "google_oauth_redirect_uri": REDIRECT,
            **overrides,
        }
    )


@pytest.fixture
def settings(monkeypatch) -> Settings:
    configured = enabled_settings()
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


@pytest.fixture
def google(monkeypatch):
    """Google's token endpoint, faked: records what it was asked and answers like Google."""
    calls: list[dict] = []
    answer = {"refresh_token": REFRESH, "scope": [oauth.UPLOAD_SCOPE]}

    def fake_fetch(flow, code):
        calls.append({"code": code, "verifier": flow.code_verifier})
        if answer.get("fail"):
            raise RuntimeError(f"invalid_grant for {code}")
        token = {"access_token": ACCESS, "token_type": "Bearer", "expires_in": 3600,
                 "expires_at": time.time() + 3600, "scope": answer["scope"]}  # fmt: skip
        if answer["refresh_token"]:
            token["refresh_token"] = answer["refresh_token"]
        flow.oauth2session.token = token

    monkeypatch.setattr(oauth, "_fetch_token", fake_fetch)
    return {"calls": calls, "answer": answer}


def sign_in(client: TestClient, email: str = "creator@example.com") -> None:
    client.cookies.clear()
    assert client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code


def start(client: TestClient) -> dict:
    response = client.post("/publishing/youtube/connect")
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["authorization_url"])
    return {"url": url, "query": {k: v[0] for k, v in parse_qs(url.query).items()}}


def callback(client: TestClient, **params):
    return client.get("/publishing/youtube/callback", params=params, follow_redirects=False)


def outcome(response) -> dict:
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == get_settings().frontend_url.rstrip("/")
    assert location.path == "/settings"
    return {k: v[0] for k, v in parse_qs(location.query).items()}


# --- starting -----


def test_the_consent_url_asks_for_upload_only_with_pkce_and_offline_access(client, settings):
    sign_in(client)
    started = start(client)
    query = started["query"]

    assert started["url"].netloc == "accounts.google.com"
    assert query["scope"] == oauth.UPLOAD_SCOPE  # nothing else: no OpenID, no read scopes
    assert query["client_id"] == CLIENT_ID and query["redirect_uri"] == REDIRECT
    assert query["access_type"] == "offline" and query["prompt"] == "consent"
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) >= 43
    assert len(query["state"]) >= 40
    assert CLIENT_SECRET not in started["url"].geturl()


def test_only_a_hash_of_the_state_and_an_encrypted_verifier_are_stored(
    client, settings, db_session: Session
):
    sign_in(client)
    state = start(client)["query"]["state"]
    [row] = db_session.scalars(select(OAuthState)).all()
    assert row.state_hash != state and len(row.state_hash) == 64
    assert row.expires_at - datetime.now(UTC) <= timedelta(minutes=10)
    assert b"v" * 10 not in row.code_verifier_ciphertext


def test_starting_again_replaces_the_pending_state(client, settings, db_session: Session):
    sign_in(client)
    first = start(client)["query"]["state"]
    second = start(client)["query"]["state"]
    assert first != second and len(db_session.scalars(select(OAuthState)).all()) == 1
    assert outcome(callback(client, state=first, code="c"))["reason"] == "invalid_state"


def test_connecting_requires_sign_in_and_an_enabled_server(client, db_session):
    assert client.post("/publishing/youtube/connect").status_code == 401
    sign_in(client)
    refused = client.post("/publishing/youtube/connect")
    assert refused.status_code == 409 and "not enabled" in refused.json()["detail"]
    assert client.get("/publishing/youtube").json() == {
        "enabled": False, "analytics_enabled": False, "connection": None,
    }  # fmt: skip


# --- the callback -----


def test_a_successful_callback_stores_an_encrypted_refresh_token(
    client, settings, google, db_session: Session
):
    sign_in(client)
    state = start(client)["query"]["state"]

    response = callback(client, state=state, code="4/0AuthCode", scope=oauth.UPLOAD_SCOPE)

    assert outcome(response) == {"youtube": "connected"}
    assert response.headers["referrer-policy"] == "no-referrer"
    for secret in (REFRESH, ACCESS, "4/0AuthCode", CLIENT_SECRET):
        assert secret not in response.headers["location"] and secret not in response.text
    [call] = google["calls"]
    assert call["code"] == "4/0AuthCode" and len(call["verifier"]) >= 43  # PKCE verifier sent
    [row] = db_session.scalars(select(PublishingConnection)).all()
    assert REFRESH.encode() not in row.refresh_token_ciphertext
    opened = TokenCipher.from_settings(settings).decrypt(
        EncryptedToken(row.refresh_token_ciphertext, row.token_key_version),
        user_id=row.user_id,
        provider="youtube",
    )
    assert opened == REFRESH and row.scopes == oauth.UPLOAD_SCOPE
    status = client.get("/publishing/youtube").json()
    assert status["enabled"] is True and status["connection"]["status"] == "connected"
    assert set(status["connection"]) == {"provider", "status", "account_title", "connected_at",
                                         "analytics_access"}  # fmt: skip
    assert status["connection"]["analytics_access"] is False  # never implied by publishing


def test_a_state_works_once(client, settings, google):
    sign_in(client)
    state = start(client)["query"]["state"]
    assert outcome(callback(client, state=state, code="c1")) == {"youtube": "connected"}
    replay = outcome(callback(client, state=state, code="c2"))
    assert replay == {"youtube": "error", "reason": "invalid_state"}
    assert len(google["calls"]) == 1


def test_a_state_belongs_to_the_user_who_started(client, settings, google, db_session):
    sign_in(client, "victim@example.com")
    state = start(client)["query"]["state"]
    sign_in(client, "attacker@example.com")  # tries to bind the victim's grant to itself
    assert outcome(callback(client, state=state, code="c"))["reason"] == "invalid_state"
    assert google["calls"] == [] and db_session.scalar(select(PublishingConnection)) is None


def test_an_expired_state_is_refused(client, settings, google, db_session: Session):
    sign_in(client)
    state = start(client)["query"]["state"]
    db_session.execute(update(OAuthState).values(expires_at=datetime.now(UTC) - timedelta(1)))
    db_session.commit()
    assert outcome(callback(client, state=state, code="c"))["reason"] == "expired"
    assert google["calls"] == []


@pytest.mark.parametrize("state", ["", "forged-state", "x" * 300])
def test_missing_or_forged_states_are_refused(client, settings, google, state):
    sign_in(client)
    start(client)
    assert outcome(callback(client, state=state, code="c"))["reason"] == "invalid_state"


def test_a_declined_consent_is_reported_and_stores_nothing(client, settings, google, db_session):
    sign_in(client)
    state = start(client)["query"]["state"]
    assert outcome(callback(client, state=state, error="access_denied"))["reason"] == "denied"
    assert google["calls"] == [] and db_session.scalar(select(PublishingConnection)) is None


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ({"refresh_token": None}, "missing_refresh_token"),
        ({"scope": ["https://www.googleapis.com/auth/userinfo.email"]}, "insufficient_scope"),
        ({"fail": True}, "exchange_failed"),
    ],  # fmt: skip
)
def test_unusable_grants_are_refused(client, settings, google, db_session, answer, reason, caplog):
    google["answer"].update(answer)
    sign_in(client)
    state = start(client)["query"]["state"]
    assert outcome(callback(client, state=state, code="4/0SecretCode"))["reason"] == reason
    assert db_session.scalar(select(PublishingConnection)) is None
    assert "4/0SecretCode" not in caplog.text and REFRESH not in caplog.text


def test_the_callback_needs_the_signed_in_user(client, settings, google):
    sign_in(client)
    state = start(client)["query"]["state"]
    client.cookies.clear()
    assert outcome(callback(client, state=state, code="c"))["reason"] == "signin_required"


def test_the_redirect_target_cannot_be_chosen_by_the_request(client, settings, google):
    sign_in(client)
    state = start(client)["query"]["state"]
    response = callback(client, state=state, code="c", redirect_uri="https://evil.example",
                        next="https://evil.example", return_to="//evil.example")  # fmt: skip
    assert "evil" not in response.headers["location"]


# --- disconnect -----


def test_disconnect_revokes_and_deletes(client, settings, google, db_session, monkeypatch):
    revoked: list[str] = []
    monkeypatch.setattr(oauth, "revoke", revoked.append)
    sign_in(client)
    state = start(client)["query"]["state"]
    callback(client, state=state, code="c")

    response = client.delete("/publishing/youtube")

    assert response.status_code == 200 and response.json() == {"revoked_with_provider": True}
    assert revoked == [REFRESH]
    assert db_session.scalar(select(PublishingConnection)) is None
    assert client.get("/publishing/youtube").json()["connection"] is None
    assert client.delete("/publishing/youtube").status_code == 404


def test_disconnect_is_scoped_to_the_signed_in_user(client, settings, google, db_session):
    sign_in(client, "owner@example.com")
    callback(client, state=start(client)["query"]["state"], code="c")
    sign_in(client, "someone-else@example.com")
    assert client.delete("/publishing/youtube").status_code == 404
    assert db_session.scalar(select(PublishingConnection)) is not None
    client.cookies.clear()
    assert client.delete("/publishing/youtube").status_code == 401


# --- configuration -----


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"google_client_id": "not-a-client"}, "GOOGLE_CLIENT_ID"),
        ({"google_client_secret": None}, "GOOGLE_CLIENT_SECRET"),
        (
            {"google_oauth_redirect_uri": "http://api.example.com/publishing/youtube/callback"},
            "https://",
        ),
        ({"google_oauth_redirect_uri": "https://api.example.com/elsewhere"}, "callback URL"),
        ({"google_oauth_redirect_uri": f"{REDIRECT}?next=x"}, "callback URL"),
        ({"publishing_token_encryption_key": None}, "ENCRYPTION_KEY"),
    ],  # fmt: skip
)
def test_enabled_publishing_needs_complete_google_settings(overrides, problem):
    with pytest.raises(ValidationError) as excinfo:
        enabled_settings(**overrides)
    message = str(excinfo.value)
    assert problem in message and CLIENT_SECRET not in message


def test_production_requires_an_https_redirect():
    from app.core.config import publishing_problems

    configured = enabled_settings()
    production = Settings.model_construct(**{**configured.model_dump(), "app_env": "production"})
    assert any("production" in p for p in publishing_problems(production))
    assert not publishing_problems(configured)  # localhost over http is fine in development


def test_starting_is_rate_limited(client, settings, monkeypatch):
    from app.core import rate_limit
    from app.core.rate_limit import DEFAULT_LIMITS, Limit, RateLimiter

    class Memory:
        counts: dict = {}

        def hit(self, key, window):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

    limiter = RateLimiter(Memory(), {**DEFAULT_LIMITS, "oauth_start": Limit(2, 3600)})
    monkeypatch.setattr(rate_limit, "get_limiter", lambda: limiter)
    sign_in(client, f"rl-{uuid.uuid4().hex[:6]}@example.com")
    assert [client.post("/publishing/youtube/connect").status_code for _ in range(3)] == [
        200,
        200,
        429,
    ]


def test_revocation_posts_the_token_to_google_and_raises_on_refusal(monkeypatch):
    import httpx

    sent: list[tuple] = []

    def fake_post(url, data, timeout):
        sent.append((url, data))
        return httpx.Response(400 if data["token"] == "bad" else 200)

    monkeypatch.setattr(httpx, "post", fake_post)
    oauth.revoke(REFRESH)
    assert sent == [(oauth.REVOKE_URI, {"token": REFRESH})]
    with pytest.raises(RuntimeError) as excinfo:
        oauth.revoke("bad")
    assert "bad" not in str(excinfo.value)
