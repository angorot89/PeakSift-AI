"""Authenticated encryption of OAuth refresh tokens (AES-256-GCM, ``cryptography``).

Stored form: a fresh 12-byte nonce followed by the ciphertext and its 16-byte tag. The
associated data binds each ciphertext to its user, provider and key version, so a token
copied to another user's row — or relabelled with another key version — fails to decrypt
instead of being used. Keys come only from the environment (``PUBLISHING_TOKEN_*``); they
are never stored in the database, returned by the API or logged.

Rotation: set a new ``PUBLISHING_TOKEN_ENCRYPTION_KEY`` with a higher
``PUBLISHING_TOKEN_KEY_VERSION`` and move the old key to ``PUBLISHING_TOKEN_PREVIOUS_KEYS``
(``"1:<key>"``). Tokens under an old key still decrypt and are re-encrypted with the
current key the next time they are used.
"""

import base64
import binascii
import os
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
KEY_BYTES = 32


class TokenKeyError(ValueError):
    """The encryption key configuration is missing or malformed."""


class TokenDecryptionError(Exception):
    """The stored token cannot be decrypted with any configured key (wrong key, tampering,
    or a ciphertext that belongs to another row)."""


def decode_key(text: str) -> bytes:
    """A 32-byte key from URL-safe or standard base64 (``openssl rand -base64 32``)."""
    normalized = text.strip().replace("-", "+").replace("_", "/")
    try:
        key = base64.b64decode(normalized + "=" * (-len(normalized) % 4), validate=True)
    except (binascii.Error, ValueError):
        raise TokenKeyError("must be base64") from None
    if len(key) != KEY_BYTES:
        raise TokenKeyError("must decode to 32 bytes")
    return key


def parse_previous_keys(text: str) -> dict[int, bytes]:
    keys: dict[int, bytes] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        version, _, key = item.partition(":")
        if not version.isdigit() or int(version) < 1:
            raise TokenKeyError("entries must be <version>:<base64 key>")
        keys[int(version)] = decode_key(key)
    return keys


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode()


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: bytes
    key_version: int


class TokenCipher:
    def __init__(self, key: bytes, version: int, previous: dict[int, bytes] | None = None) -> None:
        if len(key) != KEY_BYTES:
            raise TokenKeyError("must decode to 32 bytes")
        if version in (previous or {}):
            raise TokenKeyError("the current key version also appears among previous keys")
        self.version = version
        self._keys = {**(previous or {}), version: key}

    @classmethod
    def from_settings(cls, settings) -> "TokenCipher":
        if settings.publishing_token_encryption_key is None:
            raise TokenKeyError("PUBLISHING_TOKEN_ENCRYPTION_KEY is not set")
        previous = settings.publishing_token_previous_keys
        return cls(
            decode_key(settings.publishing_token_encryption_key.get_secret_value()),
            settings.publishing_token_key_version,
            parse_previous_keys(previous.get_secret_value()) if previous else None,
        )

    @staticmethod
    def _associated_data(user_id: uuid.UUID, provider: str, version: int) -> bytes:
        return f"peaksift:publishing:{provider}:{uuid.UUID(str(user_id))}:v{version}".encode()

    def encrypt(self, token: str, *, user_id: uuid.UUID, provider: str) -> EncryptedToken:
        if not token:
            raise ValueError("an empty token cannot be stored")
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self._keys[self.version]).encrypt(
            nonce, token.encode(), self._associated_data(user_id, provider, self.version)
        )
        return EncryptedToken(nonce + sealed, self.version)

    def decrypt(self, stored: EncryptedToken, *, user_id: uuid.UUID, provider: str) -> str:
        key = self._keys.get(stored.key_version)
        if key is None or len(stored.ciphertext) <= NONCE_BYTES + 16:
            raise TokenDecryptionError("no usable key for this token")
        nonce, sealed = stored.ciphertext[:NONCE_BYTES], stored.ciphertext[NONCE_BYTES:]
        try:
            plain = AESGCM(key).decrypt(
                nonce, sealed, self._associated_data(user_id, provider, stored.key_version)
            )
        except InvalidTag:
            raise TokenDecryptionError("the token failed authentication") from None
        return plain.decode()

    def is_current(self, stored: EncryptedToken) -> bool:
        return stored.key_version == self.version
