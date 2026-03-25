from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import pytest_asyncio
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seed_data(session: AsyncSession) -> dict:
    """Create a sample User and Issue, return their identifiers."""
    user = User(github_id=12345, username="testuser", avatar_url=None, access_token=None)
    session.add(user)
    await session.flush()

    issue = Issue(
        id="acme/widgets#1",
        org="acme",
        repo="widgets",
        number=1,
        title="Fix the widget",
        body="The widget is broken.",
        url="https://github.com/acme/widgets/issues/1",
        labels=["bug"],
        state="open",
        fetched_at=datetime.now(UTC),
    )
    session.add(issue)

    issue2 = Issue(
        id="acme/gadgets#10",
        org="acme",
        repo="gadgets",
        number=10,
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
