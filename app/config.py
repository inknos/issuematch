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

_missing = [name for name in _REQUIRED_SECRETS if not os.environ.get(name)]
if _missing:
    msg = f"Missing required environment variables: {', '.join(_missing)}"
    raise SystemExit(msg)

GITHUB_CLIENT_ID: str = os.environ["GITHUB_CLIENT_ID"]
GITHUB_CLIENT_SECRET: str = os.environ["GITHUB_CLIENT_SECRET"]
GITHUB_TOKEN: str = os.environ["GITHUB_TOKEN"]
SESSION_SECRET: str = os.environ["SESSION_SECRET"]
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./issuematch.db")
BASE_URL: str = os.environ["BASE_URL"]
