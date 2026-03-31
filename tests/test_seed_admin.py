"""Tests for the admin-seeding startup script."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from app.crypto import verify_password
from app.models import User
from app.seed_admin import ensure_admin, seed_admin
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@pytest.mark.usefixtures("setup_db")
async def test_seed_creates_admin(session: AsyncSession) -> None:
    result = await ensure_admin(session, "myadmin", "secret123")

    assert result is True
    row = (await session.execute(select(User).where(User.username == "myadmin"))).scalar_one()
    assert row.role == "admin"
    assert verify_password("secret123", row.password_hash)


@pytest.mark.usefixtures("setup_db")
async def test_seed_updates_existing_user(session: AsyncSession) -> None:
    user = User(username="existing", role="contributor")
    session.add(user)
    await session.commit()

    result = await ensure_admin(session, "existing", "newpass99")

    assert result is True
    await session.refresh(user)
    assert user.role == "admin"
    assert verify_password("newpass99", user.password_hash)


@pytest.mark.usefixtures("setup_db")
async def test_seed_skips_when_env_unset() -> None:
    with patch.dict("os.environ", {}, clear=False):
        import os  # noqa: PLC0415

        os.environ.pop("ADMIN_USERNAME", None)
        os.environ.pop("ADMIN_PASSWORD", None)
        result = await seed_admin()

    assert result is False
