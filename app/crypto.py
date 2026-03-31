"""Crypto helpers: Fernet encryption, Argon2 password hashing, SHA-256 API-token hashing."""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes as _fernet_hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pwdlib import PasswordHash

from app.config import SESSION_SECRET

_SALT = b"issuematch-token-encryption-v1"


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from the application secret."""
    kdf = PBKDF2HMAC(
        algorithm=_fernet_hashes.SHA256(),
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


# ---------------------------------------------------------------------------
# Password hashing (Argon2id via pwdlib)
# ---------------------------------------------------------------------------

_pw_hasher = PasswordHash.recommended()

DUMMY_HASH: str = _pw_hasher.hash("dummy-timing-attack-prevention")
"""Pre-computed hash verified when a user is not found, preventing timing-based
username enumeration."""


def hash_password(plaintext: str) -> str:
    """Return an Argon2id hash of *plaintext*."""
    return _pw_hasher.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True if *plaintext* matches *hashed*."""
    return _pw_hasher.verify(plaintext, hashed)


# ---------------------------------------------------------------------------
# API-token hashing (SHA-256 — tokens are high-entropy, not passwords)
# ---------------------------------------------------------------------------

_TOKEN_PREFIX_LEN = 8


def generate_api_token() -> tuple[str, str, str]:
    """Generate a new API token.

    Returns (raw_token, token_hash, token_prefix).
    """
    raw = f"im_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:_TOKEN_PREFIX_LEN]
    return raw, token_hash, prefix


def hash_api_token(raw: str) -> str:
    """Return the SHA-256 hex digest of *raw*."""
    return hashlib.sha256(raw.encode()).hexdigest()
