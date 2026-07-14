"""
Credential encryption/decryption using Fernet symmetric encryption.
Credentials are encrypted at rest and never stored as plaintext.

Usage:
    from app.core.security import CredentialEncryptor

    encryptor = CredentialEncryptor(settings.credential_encryption_key)
    encrypted = encryptor.encrypt({"username": "admin", "password": "s3cret"})
    decrypted = encryptor.decrypt(encrypted)
"""

from __future__ import annotations

import json
import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CredentialEncryptorError(Exception):
    """Raised when encryption or decryption fails."""


class CredentialEncryptor:
    """Encrypt and decrypt credential dicts using Fernet symmetric encryption."""

    def __init__(self, key: str) -> None:
        """
        Args:
            key: A Fernet key string (64 url-safe base64-encoded bytes).
                 Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        """
        if not key:
            raise CredentialEncryptorError(
                "Encryption key is empty. Set CREDENTIAL_ENCRYPTION_KEY in your environment."
            )
        try:
            key_bytes = key.encode() if isinstance(key, str) else key
            self._fernet = Fernet(key_bytes)
        except Exception as e:
            raise CredentialEncryptorError(f"Invalid encryption key: {e}") from e

    def encrypt(self, credentials: dict) -> str:
        """
        Encrypt a credentials dict to a Fernet token string.

        Args:
            credentials: Dictionary of credential key/value pairs.

        Returns:
            Encrypted string (Fernet token, base64-encoded).
        """
        try:
            plaintext = json.dumps(credentials, ensure_ascii=False).encode("utf-8")
            token = self._fernet.encrypt(plaintext)
            return token.decode("utf-8")
        except Exception as e:
            logger.error("Failed to encrypt credentials: %s", e)
            raise CredentialEncryptorError(f"Encryption failed: {e}") from e

    def decrypt(self, encrypted: str) -> dict:
        """
        Decrypt a Fernet token string back to a credentials dict.

        Args:
            encrypted: The Fernet token string from encrypt().

        Returns:
            Decrypted credentials dictionary.
        """
        try:
            token_bytes = encrypted.encode("utf-8") if isinstance(encrypted, str) else encrypted
            plaintext = self._fernet.decrypt(token_bytes)
            return json.loads(plaintext.decode("utf-8"))
        except InvalidToken as e:
            logger.error("Decryption failed — invalid token or wrong key: %s", e)
            raise CredentialEncryptorError(
                "Decryption failed: invalid token or wrong encryption key."
            ) from e
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            raise CredentialEncryptorError(f"Decryption failed: {e}") from e


def generate_key() -> str:
    """Generate a new Fernet encryption key. Call once during initial setup."""
    return Fernet.generate_key().decode("utf-8")
