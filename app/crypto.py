"""Symmetric encryption helpers for storing GitHub API tokens at rest."""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import SESSION_SECRET

_SALT = b"issuematch-token-encryption-v1"


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from the application secret."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


_fernet = Fernet(_derive_key(SESSION_SECRET))


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string and return the ciphertext as a UTF-8 string."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a previously encrypted token, returning the original plaintext."""
    return _fernet.decrypt(ciphertext.encode()).decode()
