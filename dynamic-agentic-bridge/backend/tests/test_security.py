"""
Unit tests for credential encryption/decryption.
"""

import json

import pytest

from app.core.security import (
    CredentialEncryptor,
    CredentialEncryptorError,
    generate_key,
)


@pytest.fixture
def encryption_key() -> str:
    """Generate a fresh Fernet key for each test."""
    return generate_key()


@pytest.fixture
def encryptor(encryption_key: str) -> CredentialEncryptor:
    return CredentialEncryptor(encryption_key)


class TestCredentialEncryptor:
    def test_encrypt_decrypt_roundtrip(self, encryptor: CredentialEncryptor):
        creds = {"username": "admin", "password": "p@ssw0rd!"}
        encrypted = encryptor.encrypt(creds)
        decrypted = encryptor.decrypt(encrypted)
        assert decrypted == creds

    def test_encrypted_output_is_string(self, encryptor: CredentialEncryptor):
        creds = {"token": "abc-123"}
        encrypted = encryptor.encrypt(creds)
        assert isinstance(encrypted, str)
        assert encrypted != json.dumps(creds)  # Must not be plaintext

    def test_different_encryptions_produce_different_tokens(
        self, encryptor: CredentialEncryptor
    ):
        creds = {"key": "value"}
        e1 = encryptor.encrypt(creds)
        e2 = encryptor.encrypt(creds)
        # Fernet includes a timestamp, so tokens differ even for same input
        assert e1 != e2

    def test_wrong_key_fails_decryption(self, encryption_key: str):
        creds = {"secret": "data"}
        encryptor1 = CredentialEncryptor(encryption_key)
        encrypted = encryptor1.encrypt(creds)

        key2 = generate_key()
        encryptor2 = CredentialEncryptor(key2)
        with pytest.raises(CredentialEncryptorError, match="Decryption failed"):
            encryptor2.decrypt(encrypted)

    def test_empty_key_raises(self):
        with pytest.raises(CredentialEncryptorError, match="empty"):
            CredentialEncryptor("")

    def test_invalid_key_format_raises(self):
        with pytest.raises(CredentialEncryptorError, match="Invalid"):
            CredentialEncryptor("not-a-valid-fernet-key!!!")

    def test_empty_dict_roundtrip(self, encryptor: CredentialEncryptor):
        encrypted = encryptor.encrypt({})
        assert encryptor.decrypt(encrypted) == {}

    def test_nested_dict_roundtrip(self, encryptor: CredentialEncryptor):
        creds = {
            "api_key": "sk-123",
            "config": {"region": "us-east-1", "nested": True},
        }
        encrypted = encryptor.encrypt(creds)
        assert encryptor.decrypt(encrypted) == creds

    def test_unicode_credentials_roundtrip(self, encryptor: CredentialEncryptor):
        creds = {"username": "admin", "password": "pässwörd_日本語"}
        encrypted = encryptor.encrypt(creds)
        assert encryptor.decrypt(encrypted) == creds

    def test_corrupted_token_fails(self, encryptor: CredentialEncryptor):
        encrypted = encryptor.encrypt({"key": "val"})
        # Corrupt the token by flipping a character
        corrupted = encrypted[:-4] + "XXXX"
        with pytest.raises(CredentialEncryptorError, match="Decryption failed"):
            encryptor.decrypt(corrupted)


class TestGenerateKey:
    def test_generates_valid_key(self):
        key = generate_key()
        assert isinstance(key, str)
        assert len(key) > 20
        # Should be usable immediately
        enc = CredentialEncryptor(key)
        assert enc.encrypt({"test": True})

    def test_keys_are_unique(self):
        keys = {generate_key() for _ in range(10)}
        assert len(keys) == 10  # All unique
