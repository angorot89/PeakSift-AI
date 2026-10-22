# ruff: noqa: F811 - the google fixture imported from test_youtube_oauth is a parameter here
"""The explicit analytics permission upgrade: never implied by publishing, read-only scopes
on top of the upload the creator already granted, checked against what Google actually
granted, and never at the expense of a working publishing connection. No network."""

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.api import publishing as api
from app.models import OAuthState, PublishingConnection
from app.services.publishing import youtube_oauth as oauth
from app.services.publishing.tokens import EncryptedToken, TokenCipher
from tests.test_youtube_oauth import (  # noqa: F401 - google is a fixture
    ACCESS,
    CLIENT_SECRET,
    REFRESH,
    callback,
    enabled_settings,
    google,
    sign_in,
    start,
)

ALL = [oauth.UPLOAD_SCOPE, oauth.READONLY_SCOPE, oauth.ANALYTICS_SCOPE]
UPGRADED = "1//0gUpgradedRefreshToken"


@pytest.fixture
def settings(monkeypatch):
    configured = enabled_settings(youtube_analytics_enabled=True)
    monkeypatch.setattr(api, "get_settings", lambda: configured)
    return configured


def outcome(response) -> dict:
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/settings"
    return {k: v[0] for k, v in parse_qs(location.query).items()}


def start_analytics(client) -> dict:
    response = client.post("/publishing/youtube/analytics/connect")
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["authorization_url"])
    return {k: v[0] for k, v in parse_qs(url.query).items()}


def connected(client, google, title="My channel", db=None) -> PublishingConnection:
    """A creator with an upload-only connection (as every V1.0–V1.3 creator has)."""
    sign_in(client)
    assert outcome(callback(client, state=start(client)["query"]["state"], code="c")) == {
        "youtube": "connected"
    }
    row = db.scalar(select(PublishingConnection))
    row.account_title = title  # learned from the first upload
    db.commit()
    return row


def token_of(row, settings) -> str:
    return TokenCipher.from_settings(settings).decrypt(
        EncryptedToken(row.refresh_token_ciphertext, row.token_key_version),
        user_id=row.user_id,
        provider="youtube",
    )


def grant(google, scopes, refresh=UPGRADED):
    google["answer"].update({"scope": scopes, "refresh_token": refresh})


# --- starting ----------------------------------------------------------------------------------


def test_the_upgrade_asks_for_read_only_analytics_on_top_of_upload(client, settings, google,
                                                                   db_session):  # fmt: skip
    connected(client, google, db=db_session)
    query = start_analytics(client)
    assert query["scope"].split() == ALL  # upload (already granted) + two read-only scopes
    assert query["access_type"] == "offline" and query["prompt"] == "consent"
    assert query["code_challenge_method"] == "S256"
    [state] = db_session.scalars(select(OAuthState)).all()
    assert state.purpose == "analytics"


def test_publishing_still_asks_for_upload_only(client, settings):
    sign_in(client)
    assert start(client)["query"]["scope"] == oauth.UPLOAD_SCOPE


def test_the_upgrade_needs_sign_in_and_an_enabled_server(client, monkeypatch):
    assert client.post("/publishing/youtube/analytics/connect").status_code == 401
    sign_in(client)
    for configured in (enabled_settings(), enabled_settings(youtube_publishing_enabled=False)):
        monkeypatch.setattr(api, "get_settings", lambda c=configured: c)
        refused = client.post("/publishing/youtube/analytics/connect")
        assert refused.status_code == 409 and "analytics is not enabled" in refused.json()["detail"]
        assert client.get("/publishing/youtube").json()["analytics_enabled"] is False


def test_status_reports_analytics_access_honestly(client, settings, google, db_session):
    connected(client, google, db=db_session)
    status = client.get("/publishing/youtube").json()
    assert status["analytics_enabled"] is True
    assert status["connection"]["analytics_access"] is False  # "not connected" until granted
    assert "scopes" not in status["connection"]


# --- the callback ------------------------------------------------------------------------------


def test_a_granted_upgrade_replaces_the_token_and_keeps_the_channel(
    client, settings, google, db_session, caplog
):
    row = connected(client, google, db=db_session)
    state = start_analytics(client)["state"]
    grant(google, ALL)
    response = callback(client, state=state, code="4/0UpgradeCode")
    assert outcome(response) == {"analytics": "connected"}
    db_session.expire_all()
    row = db_session.scalar(select(PublishingConnection))
    assert token_of(row, settings) == UPGRADED and set(row.scopes.split()) == set(ALL)
    assert row.account_title == "My channel" and row.status == "connected"
    connection = client.get("/publishing/youtube").json()["connection"]
    assert connection["analytics_access"] is True and connection["account_title"] == "My channel"
    for secret in (UPGRADED, REFRESH, ACCESS, "4/0UpgradeCode", CLIENT_SECRET):
        assert secret not in response.headers["location"] and secret not in caplog.text


@pytest.mark.parametrize(
    ("scopes", "reason"),
    [
        ([oauth.UPLOAD_SCOPE], "analytics_not_granted"),  # the creator unticked both
        ([oauth.UPLOAD_SCOPE, oauth.READONLY_SCOPE], "analytics_not_granted"),  # one of two
        ([oauth.READONLY_SCOPE, oauth.ANALYTICS_SCOPE], "insufficient_scope"),  # unticked upload
    ],
    ids=["no-analytics", "partial", "no-upload"],
)
def test_a_partial_grant_leaves_publishing_exactly_as_it_was(client, settings, google, db_session,
                                                             scopes, reason):  # fmt: skip
    row = connected(client, google, db=db_session)
    before = (row.refresh_token_ciphertext, row.scopes, row.account_title)
    state = start_analytics(client)["state"]
    grant(google, scopes)
    assert outcome(callback(client, state=state, code="c")) == {
        "analytics": "error", "reason": reason
    }  # fmt: skip
    db_session.expire_all()
    row = db_session.scalar(select(PublishingConnection))
    assert (row.refresh_token_ciphertext, row.scopes, row.account_title) == before
    assert token_of(row, settings) == REFRESH  # publishing keeps working
    assert client.get("/publishing/youtube").json()["connection"]["analytics_access"] is False


def test_a_declined_upgrade_changes_nothing(client, settings, google, db_session):
    row = connected(client, google, db=db_session)
    before = row.refresh_token_ciphertext
    state = start_analytics(client)["state"]
    assert outcome(callback(client, state=state, error="access_denied")) == {
        "analytics": "error", "reason": "denied"
    }  # fmt: skip
    db_session.expire_all()
    assert db_session.scalar(select(PublishingConnection)).refresh_token_ciphertext == before


def test_the_purpose_comes_from_the_stored_state_never_the_request(client, settings, google,
                                                                   db_session):  # fmt: skip
    connected(client, google, db=db_session)
    state = start(client)["query"]["state"]  # a publishing reconnect
    grant(google, ALL)  # even if Google returned more
    response = callback(client, state=state, code="c", purpose="analytics", scope=" ".join(ALL))
    # Handled as the publishing reconnect it was started as (its account title is not kept).
    assert outcome(response) == {"youtube": "connected"}
    assert db_session.scalar(select(PublishingConnection)).account_title == ""


def test_reconnecting_for_publishing_asks_for_upload_only_again(client, settings, google,
                                                                db_session):  # fmt: skip
    connected(client, google, db=db_session)
    state = start_analytics(client)["state"]
    grant(google, ALL)
    callback(client, state=state, code="c")
    assert client.get("/publishing/youtube").json()["connection"]["analytics_access"] is True
    state = start(client)["query"]["state"]
    grant(google, [oauth.UPLOAD_SCOPE], refresh="1//0gReconnected")
    callback(client, state=state, code="c")
    # The new grant is upload only: analytics shows as not connected again, honestly.
    assert client.get("/publishing/youtube").json()["connection"]["analytics_access"] is False


def test_an_upgrade_started_before_analytics_was_turned_off_is_refused(client, google, db_session,
                                                                       monkeypatch):  # fmt: skip
    on = enabled_settings(youtube_analytics_enabled=True)
    monkeypatch.setattr(api, "get_settings", lambda: on)
    row = connected(client, google, db=db_session)
    before = row.refresh_token_ciphertext
    state = start_analytics(client)["state"]
    off = enabled_settings(publishing_token_encryption_key=on.publishing_token_encryption_key)
    monkeypatch.setattr(api, "get_settings", lambda: off)
    grant(google, ALL)
    assert outcome(callback(client, state=state, code="c")) == {
        "analytics": "error", "reason": "disabled"
    }  # fmt: skip
    db_session.expire_all()
    assert db_session.scalar(select(PublishingConnection)).refresh_token_ciphertext == before


def test_a_creator_without_a_connection_can_grant_both_at_once(client, settings, google,
                                                               db_session):  # fmt: skip
    sign_in(client)
    state = start_analytics(client)["state"]
    grant(google, ALL)
    assert outcome(callback(client, state=state, code="c")) == {"analytics": "connected"}
    connection = client.get("/publishing/youtube").json()["connection"]
    assert connection["status"] == "connected" and connection["analytics_access"] is True


# --- access tokens are scoped per use ----------------------------------------------------------


def test_each_use_asks_google_for_its_own_scopes_only(monkeypatch, settings):
    """Publishing refreshes with upload only and analytics with the read scopes only, even
    when the stored grant holds all three."""
    from google.oauth2.credentials import Credentials

    from app.services.performance.youtube import YouTubeMetricsProvider
    from app.services.publishing.youtube import YouTubeProvider

    asked: list[list[str]] = []

    def fake_refresh(self, request):
        asked.append(list(self.scopes))
        self.token = "ya29.scoped"

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    YouTubeProvider.from_settings(settings).authorize(UPGRADED)
    YouTubeMetricsProvider.from_settings(settings).authorize(UPGRADED)
    assert asked == [[oauth.UPLOAD_SCOPE], [oauth.READONLY_SCOPE, oauth.ANALYTICS_SCOPE]]


def test_has_analytics_access():
    assert oauth.has_analytics_access(" ".join(ALL))
    assert not oauth.has_analytics_access(oauth.UPLOAD_SCOPE)
    assert not oauth.has_analytics_access([oauth.UPLOAD_SCOPE, oauth.ANALYTICS_SCOPE])
