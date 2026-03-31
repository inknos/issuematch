"""Environment configuration and secret validation."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_REQUIRED_SECRETS = ("SESSION_SECRET",)


def validate_secrets() -> None:
    """Raise SystemExit if any required secret is missing. Call at app startup."""
    missing = [name for name in _REQUIRED_SECRETS if not os.environ.get(name)]
    if missing:
        msg = f"Missing required environment variables: {', '.join(missing)}"
        raise SystemExit(msg)


SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "")

DB_HOST: str = os.environ.get("DB_HOST", "localhost")
DB_PORT: str = os.environ.get("DB_PORT", "5432")
DB_USER: str = os.environ.get("DB_USER", "issuematch")
DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "")
DB_NAME: str = os.environ.get("DB_NAME", "issuematch")

DATABASE_URL: str = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
