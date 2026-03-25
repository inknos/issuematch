from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_REQUIRED_SECRETS = (
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "GITHUB_TOKEN",
    "SESSION_SECRET",
    "BASE_URL",
)


def validate_secrets() -> None:
    """Raise SystemExit if any required secret is missing. Call at app startup."""
    missing = [name for name in _REQUIRED_SECRETS if not os.environ.get(name)]
    if missing:
        msg = f"Missing required environment variables: {', '.join(missing)}"
        raise SystemExit(msg)


GITHUB_CLIENT_ID: str = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET: str = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "")
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./issuematch.db")
BASE_URL: str = os.environ.get("BASE_URL", "")
