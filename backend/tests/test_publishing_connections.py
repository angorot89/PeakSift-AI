"""YouTube connections: refresh tokens sealed with AES-256-GCM, bound to their row, keys from
configuration only, one connection per user, disconnect that always deletes the token."""

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ConnectionStatus, PublishingConnection, User
from app.services.publishing import connections
from app.services.publishing.tokens import (
    EncryptedToken,
    TokenCipher,
    TokenDecryptionError,
    TokenKeyError,
    decode_key,
    generate_key,
)

REFRESH = "1//0gRealLookingRefreshTokenValue-abc"
KEY_A, KEY_B = generate_key(), generate_key()


def cipher(key: str = KEY_A, version: int = 1, previous: dict | None = None) -> TokenCipher:
    return TokenCipher(decode_key(key), version, previous)


def user(db: Session) -> User:
    row = User(email=f"c-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db.add(row)
    db.commit()
    return row


# --- the cipher -----


def test_tokens_round_trip_and_never_appear_in_the_ciphertext():
    owner = uuid.uuid4()
    sealed = cipher().encrypt(REFRESH, user_id=owner, provider="youtube")
    assert REFRESH.encode() not in sealed.ciphertext and sealed.key_version == 1
    assert cipher().decrypt(sealed, user_id=owner, provider="youtube") == REFRESH
    again = cipher().encrypt(REFRESH, user_id=owner, provider="youtube")
    assert again.ciphertext != sealed.ciphertext  # a fresh nonce every time


@pytest.mark.parametrize("change", ["user", "provider", "version", "tamper", "truncate", "key"])
def test_a_token_opens_only_for_its_own_row_and_key(change):
    owner = uuid.uuid4()
    sealed = cipher().encrypt(REFRESH, user_id=owner, provider="youtube")
    user_id, provider, key, stored = owner, "youtube", KEY_A, sealed
    if change == "user":
        user_id = uuid.uuid4()  # copied to another user's row
    elif change == "provider":
        provider = "other"
    elif change == "version":
        stored = EncryptedToken(sealed.ciphertext, 2)  # relabelled
        key = None
    elif change == "tamper":
        flipped = bytearray(sealed.ciphertext)
        flipped[-1] ^= 1
        stored = EncryptedToken(bytes(flipped), 1)
    elif change == "truncate":
        stored = EncryptedToken(sealed.ciphertext[:20], 1)
    else:
        key = KEY_B
    reader = cipher(KEY_A, 1, {2: decode_key(KEY_B)}) if key is None else cipher(key)
    with pytest.raises(TokenDecryptionError):
        reader.decrypt(stored, user_id=user_id, provider=provider)


def test_rotation_keeps_old_tokens_readable():
    owner = uuid.uuid4()
    old = cipher(KEY_A, 1).encrypt(REFRESH, user_id=owner, provider="youtube")
    rotated = cipher(KEY_B, 2, {1: decode_key(KEY_A)})
    assert rotated.decrypt(old, user_id=owner, provider="youtube") == REFRESH
    assert not rotated.is_current(old)


@pytest.mark.parametrize("bad", ["", "not base64 !!", "c2hvcnQ=", generate_key() + "AAAA"])
def test_malformed_keys_are_refused(bad):
    with pytest.raises(TokenKeyError):
        decode_key(bad)


def test_standard_base64_keys_from_openssl_are_accepted():
    import base64
    import os

    raw = os.urandom(32)
    assert decode_key(base64.b64encode(raw).decode()) == raw


# --- settings -----


def settings(**overrides) -> dict:
    return {**get_settings().model_dump(), **overrides}


def test_enabling_publishing_requires_a_key():
    with pytest.raises(ValidationError) as excinfo:
        Settings(**settings(youtube_publishing_enabled=True, publishing_token_encryption_key=None))
    assert "PUBLISHING_TOKEN_ENCRYPTION_KEY is required" in str(excinfo.value)


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"publishing_token_encryption_key": "short-secret-value"}, "ENCRYPTION_KEY"),
        ({"publishing_token_previous_keys": "x:short-secret-value"}, "PREVIOUS_KEYS"),
        (
            {
                "publishing_token_encryption_key": KEY_A,
                "publishing_token_previous_keys": f"1:{KEY_B}",
            },
            "KEY_VERSION",
        ),  # fmt: skip
    ],
)
def test_key_settings_are_validated_without_echoing_values(overrides, problem):
    with pytest.raises(ValidationError) as excinfo:
        Settings(**settings(**overrides))
    message = str(excinfo.value)
    assert problem in message
    assert "short-secret-value" not in message and KEY_A not in message and KEY_B not in message


def test_keys_never_appear_in_the_settings_repr():
    configured = Settings(**settings(publishing_token_encryption_key=KEY_A))
    assert KEY_A not in repr(configured) and KEY_A not in str(configured.model_dump())
    assert TokenCipher.from_settings(configured).version == 1


# --- the model -----


def test_one_connection_per_user(db_session: Session):
    owner = user(db_session)
    connections.save_connection(
        db_session, cipher(), user_id=owner.id, refresh_token=REFRESH,
        account_id="UC1", account_title="Channel", scopes=["s"],
    )  # fmt: skip
    duplicate = PublishingConnection(
        user_id=owner.id, provider="youtube", account_id="UC2", account_title="Other",
        scopes="s", refresh_token_ciphertext=b"x" * 40, token_key_version=1,
    )  # fmt: skip
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    ("field", "value"), [("provider", "tiktok"), ("status", "active"), ("token_key_version", 0)]
)
def test_the_database_refuses_unknown_providers_and_states(db_session: Session, field, value):
    owner = user(db_session)
    row = PublishingConnection(user_id=owner.id, provider="youtube", account_id="UC1",
                               account_title="C", scopes="s",
                               refresh_token_ciphertext=b"x" * 40, token_key_version=1)  # fmt: skip
    setattr(row, field, value)
    db_session.add(row)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_repr_never_shows_the_ciphertext(db_session: Session):
    owner = user(db_session)
    row = connections.save_connection(db_session, cipher(), user_id=owner.id,
                                      refresh_token=REFRESH, account_id="UC1",
                                      account_title="C", scopes=["s"])  # fmt: skip
    assert "ciphertext" not in repr(row) and "\\x" not in repr(row)


def test_deleting_the_user_deletes_the_connection(db_session: Session):
    owner = user(db_session)
    connections.save_connection(db_session, cipher(), user_id=owner.id, refresh_token=REFRESH,
                                account_id="UC1", account_title="C", scopes=["s"])  # fmt: skip
    db_session.delete(owner)
    db_session.commit()
    assert db_session.scalar(select(PublishingConnection)) is None


# --- the service -----


def test_reconnecting_replaces_the_connection(db_session: Session):
    owner = user(db_session)
    first = connections.save_connection(db_session, cipher(), user_id=owner.id,
                                        refresh_token="1//first-token-value", account_id="UC1",
                                        account_title="Old name", scopes=["a"])  # fmt: skip
    first.status = ConnectionStatus.NEEDS_RECONNECT
    db_session.commit()
    second = connections.save_connection(db_session, cipher(), user_id=owner.id,
                                         refresh_token="1//second-token-value",
                                         account_id="UC2", account_title="New name",
                                         scopes=["b", "a", "b"])  # fmt: skip
    assert second.id == first.id and second.status == ConnectionStatus.CONNECTED
    assert (second.account_id, second.account_title, second.scopes) == ("UC2", "New name", "a b")
    assert connections.refresh_token_of(db_session, cipher(), second) == "1//second-token-value"


def test_tokens_under_an_old_key_are_re_encrypted_when_used(db_session: Session):
    owner = user(db_session)
    row = connections.save_connection(db_session, cipher(KEY_A, 1), user_id=owner.id,
                                      refresh_token=REFRESH, account_id="UC1",
                                      account_title="C", scopes=["s"])  # fmt: skip
    rotated = cipher(KEY_B, 2, {1: decode_key(KEY_A)})
    assert connections.refresh_token_of(db_session, rotated, row) == REFRESH
    db_session.refresh(row)
    assert row.token_key_version == 2
    assert connections.refresh_token_of(db_session, cipher(KEY_B, 2), row) == REFRESH


def test_disconnect_revokes_then_always_deletes(db_session: Session):
    owner = user(db_session)
    row = connections.save_connection(db_session, cipher(), user_id=owner.id,
                                      refresh_token=REFRESH, account_id="UC1",
                                      account_title="C", scopes=["s"])  # fmt: skip
    revoked: list[str] = []
    assert connections.disconnect(db_session, cipher(), row, revoked.append) is True
    assert revoked == [REFRESH]
    assert connections.get_connection(db_session, owner.id) is None


def test_disconnect_deletes_even_when_the_provider_fails(db_session: Session, caplog):
    owner = user(db_session)
    row = connections.save_connection(db_session, cipher(), user_id=owner.id,
                                      refresh_token=REFRESH, account_id="UC1",
                                      account_title="C", scopes=["s"])  # fmt: skip

    def unreachable(token: str) -> None:
        raise ConnectionError(f"revoke failed for {token}")

    assert connections.disconnect(db_session, cipher(), row, unreachable) is False
    assert connections.get_connection(db_session, owner.id) is None
    assert REFRESH not in caplog.text and "ConnectionError" in caplog.text
