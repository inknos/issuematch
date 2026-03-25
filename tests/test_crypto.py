"""Tests for the token encryption/decryption helpers."""

from __future__ import annotations

import pytest
from app.crypto import decrypt_token, encrypt_token
from cryptography.fernet import InvalidToken


def test_round_trip() -> None:
    token = "ghp_abc123XYZ"
    encrypted = encrypt_token(token)
    assert decrypt_token(encrypted) == token


def test_ciphertext_differs_from_plaintext() -> None:
    token = "ghp_secret"
    encrypted = encrypt_token(token)
    assert encrypted != token


def test_different_plaintexts_produce_different_ciphertexts() -> None:
    a = encrypt_token("token_a")
    b = encrypt_token("token_b")
    assert a != b


def test_decrypt_invalid_ciphertext_raises() -> None:
    with pytest.raises(InvalidToken):
        decrypt_token("not-valid-ciphertext")
