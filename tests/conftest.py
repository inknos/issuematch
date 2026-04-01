from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from app.auth import get_current_role, get_current_uid
from app.models import Base, Issue, User
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

engine = create_async_engine("sqlite+aiosqlite://", echo=False)
async_test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_test_session() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with async_test_session() as s:
        yield s


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.database import get_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415

    app.dependency_overrides[get_session] = _override_get_session
    app.state.session_factory = async_test_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth() -> Generator[_AuthOverrider, None, None]:
    """Provides a context manager to override auth dependencies for testing.

    Usage::

        with auth(user_id=1, role="admin"):
            resp = await client.get("/api/admin/users/json")
    """
    from app.main import app  # noqa: PLC0415

    overrider = _AuthOverrider(app)
    yield overrider
    overrider.clear()


class _AuthOverrider:
    """Helper that manages dependency_overrides for get_current_uid / get_current_role."""

    def __init__(self, app) -> None:  # noqa: ANN001
        self._app = app

    @contextmanager
    def __call__(self, user_id: int, role: str) -> Generator[None, None, None]:
        self._app.dependency_overrides[get_current_uid] = lambda: user_id
        self._app.dependency_overrides[get_current_role] = lambda: role
        try:
            yield
        finally:
            self._app.dependency_overrides.pop(get_current_uid, None)
            self._app.dependency_overrides.pop(get_current_role, None)

    def clear(self) -> None:
        self._app.dependency_overrides.pop(get_current_uid, None)
        self._app.dependency_overrides.pop(get_current_role, None)


@pytest_asyncio.fixture
async def seed_data(session: AsyncSession) -> dict:
    """Create a sample User (contributor) and Issues, return their identifiers."""
    user = User(
        username="testuser",
        avatar_url=None,
        role="contributor",
    )
    session.add(user)
    await session.flush()

    issue = Issue(
        id="acme/widgets/issue/1",
        org="acme",
        repo="widgets",
        number=1,
        type="issue",
        title="Fix the widget",
        body="The widget is broken.",
        url="https://github.com/acme/widgets/issues/1",
        labels=["bug"],
        state="open",
        fetched_at=datetime.now(UTC),
    )
    session.add(issue)

    issue2 = Issue(
        id="acme/gadgets/issue/10",
        org="acme",
        repo="gadgets",
        number=10,
        type="issue",
        title="Add gadget support",
        body=None,
        url="https://github.com/acme/gadgets/issues/10",
        labels=[],
        state="open",
        fetched_at=datetime.now(UTC),
    )
    session.add(issue2)
    await session.commit()

    return {
        "user_id": user.id,
        "issue_id": issue.id,
        "issue_id_2": issue2.id,
    }


@pytest_asyncio.fixture
async def admin_user(session: AsyncSession) -> dict:
    """Create an admin user, return their identifiers."""
    user = User(
        username="adminuser",
        avatar_url=None,
        role="admin",
    )
    session.add(user)
    await session.commit()
    return {"user_id": user.id, "username": user.username}


@pytest_asyncio.fixture
async def maintainer_user(session: AsyncSession) -> dict:
    """Create a maintainer user, return their identifiers."""
    user = User(
        username="maintaineruser",
        avatar_url=None,
        role="maintainer",
    )
    session.add(user)
    await session.commit()
    return {"user_id": user.id, "username": user.username}
