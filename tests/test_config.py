from __future__ import annotations

import pytest
from app.config import validate_secrets


def test_validate_secrets_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "GITHUB_TOKEN",
        "SESSION_SECRET",
        "BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit, match="GITHUB_CLIENT_ID"):
        validate_secrets()


def test_validate_secrets_passes_when_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_CLIENT_ID", "id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_tok")
    monkeypatch.setenv("SESSION_SECRET", "sess")
    monkeypatch.setenv("BASE_URL", "http://localhost")

    validate_secrets()


def test_validate_secrets_reports_all_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "GITHUB_TOKEN",
        "SESSION_SECRET",
        "BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit, match="SESSION_SECRET"):
        validate_secrets()
