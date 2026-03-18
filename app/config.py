from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


GITHUB_CLIENT_ID: str = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET: str = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "change-me")
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./issuematch.db")
BASE_URL: str = os.environ.get("BASE_URL", "http://localhost:8000")
