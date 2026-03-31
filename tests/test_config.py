from __future__ import annotations

import pytest
from app.config import validate_secrets


def test_validate_secrets_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    with pytest.raises(SystemExit, match="SESSION_SECRET"):
        validate_secrets()


def test_validate_secrets_passes_when_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SECRET", "sess")

    validate_secrets()
