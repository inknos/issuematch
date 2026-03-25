"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session and close it on exit."""
    async with async_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
