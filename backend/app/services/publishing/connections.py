"""Storing, using and removing a user's publishing connection.

Tokens cross this module's boundary only as plaintext handed to the provider client for a
single call: they are encrypted before they reach the database, never placed in a response
and never logged. Disconnecting revokes the refresh token with the provider on a
best-effort basis and **always** deletes it here, whether or not the provider answered.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConnectionStatus, PublishingConnection, PublishingProvider
from app.services.publishing.tokens import EncryptedToken, TokenCipher

logger = logging.getLogger(__name__)


def get_connection(
    db: Session, user_id: uuid.UUID, provider: PublishingProvider = PublishingProvider.YOUTUBE
) -> PublishingConnection | None:
    """The user's connection to one platform (YouTube unless another is named)."""
    return db.scalar(
        select(PublishingConnection).where(
            PublishingConnection.user_id == user_id,
            PublishingConnection.provider == PublishingProvider(provider).value,
        )
    )


def list_connections(db: Session, user_id: uuid.UUID) -> dict[str, PublishingConnection]:
    """Every platform the user has connected, by platform key."""
    rows = db.scalars(select(PublishingConnection).where(PublishingConnection.user_id == user_id))
    return {row.provider: row for row in rows}


def save_connection(
    db: Session,
    cipher: TokenCipher,
    *,
    user_id: uuid.UUID,
    refresh_token: str,
    account_id: str,
    account_title: str,
    scopes: list[str],
    provider: PublishingProvider = PublishingProvider.YOUTUBE,
) -> PublishingConnection:
    """Create the user's connection to this platform, or replace it (one per platform)."""
    provider = PublishingProvider(provider)
    sealed = cipher.encrypt(refresh_token, user_id=user_id, provider=provider.value)
    connection = get_connection(db, user_id, provider) or PublishingConnection(user_id=user_id)
    connection.provider = provider.value
    connection.status = ConnectionStatus.CONNECTED
    connection.account_id = account_id[:128]
    connection.account_title = (account_title or "")[:255]  # learned on first upload
    connection.scopes = " ".join(sorted(set(scopes)))[:1024]
    connection.refresh_token_ciphertext = sealed.ciphertext
    connection.token_key_version = sealed.key_version
    connection.connected_at = datetime.now(UTC)
    db.add(connection)
    db.commit()
    return connection


def _stored(connection: PublishingConnection) -> EncryptedToken:
    return EncryptedToken(connection.refresh_token_ciphertext, connection.token_key_version)


def refresh_token_of(db: Session, cipher: TokenCipher, connection: PublishingConnection) -> str:
    """The plaintext refresh token for one provider call. A token sealed with an older key
    is re-encrypted with the current one (lazy key rotation). Raises
    ``TokenDecryptionError`` when no configured key opens it."""
    token = cipher.decrypt(
        _stored(connection), user_id=connection.user_id, provider=connection.provider
    )
    if not cipher.is_current(_stored(connection)):
        sealed = cipher.encrypt(token, user_id=connection.user_id, provider=connection.provider)
        connection.refresh_token_ciphertext = sealed.ciphertext
        connection.token_key_version = sealed.key_version
        db.commit()
    return token


def store_rotated_token(
    db: Session, cipher: TokenCipher, connection: PublishingConnection, refresh_token: str
) -> None:
    """Keep the refresh token a platform issued in place of the one just used.

    Some platforms rotate refresh tokens: the old one stops working the moment a new one is
    returned, so the new one is committed before anything else is done with the access token.
    """
    sealed = cipher.encrypt(refresh_token, user_id=connection.user_id, provider=connection.provider)
    connection.refresh_token_ciphertext = sealed.ciphertext
    connection.token_key_version = sealed.key_version
    db.commit()


def mark_needs_reconnect(db: Session, connection: PublishingConnection) -> None:
    connection.status = ConnectionStatus.NEEDS_RECONNECT
    db.commit()


def disconnect(
    db: Session,
    cipher: TokenCipher | None,
    connection: PublishingConnection,
    revoke: Callable[[str], None],
) -> bool:
    """Revoke with the provider (best effort), then delete the connection and its token.
    Returns whether the provider confirmed the revocation."""
    revoked = False
    try:
        if cipher is None:
            raise RuntimeError("no token key configured")
        revoke(refresh_token_of(db, cipher, connection))
        revoked = True
    except Exception as error:  # noqa: BLE001 — the local token is deleted regardless
        logger.warning("Provider token revocation failed: %s", type(error).__name__)
    db.delete(connection)
    db.commit()
    return revoked
