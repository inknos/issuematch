"""Create or update an admin user from ADMIN_USERNAME / ADMIN_PASSWORD env vars.

Run as: ``python -m app.seed_admin``

Designed to execute between ``alembic upgrade head`` and ``uvicorn`` in the
container entrypoint.  If either env var is unset the script exits silently.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.crypto import hash_password
from app.models import Role, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_admin(session: AsyncSession, username: str, password: str) -> bool:
    """Create or update an admin user with the given credentials.

    Returns True if a user was created or updated.
    """
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=Role.admin.value,
        )
        session.add(user)
        print(f"seed_admin: created admin user '{username}'")  # noqa: T201
    else:
        user.password_hash = hash_password(password)
        user.role = Role.admin.value
        print(f"seed_admin: updated admin user '{username}'")  # noqa: T201

    await session.commit()
    return True


async def seed_admin() -> bool:
    """Read env vars and seed the admin user. Returns True if a user was changed."""
    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()

    if not username or not password:
        return False

    from app.database import async_session  # noqa: PLC0415

    async with async_session() as session:
        return await ensure_admin(session, username, password)


def main() -> None:
    """Entry-point when invoked as ``python -m app.seed_admin``."""
    changed = asyncio.run(seed_admin())
    if not changed:
        print("seed_admin: ADMIN_USERNAME / ADMIN_PASSWORD not set — skipped")  # noqa: T201
    sys.exit(0)


if __name__ == "__main__":
    main()
