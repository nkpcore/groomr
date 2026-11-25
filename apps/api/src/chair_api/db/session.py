"""Async SQLAlchemy engine and request-scoped session helpers."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from chair_api.core.config import get_settings


def create_engine_and_sessionmaker(
    database_url: str | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    url = database_url or get_settings().database_url
    engine = create_async_engine(url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, session_factory


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session from the shared app-lifespan engine pool."""
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is not None:
        async with session_factory() as session:
            yield session
        return

    engine, fallback_factory = create_engine_and_sessionmaker()
    try:
        async with fallback_factory() as session:
            yield session
    finally:
        await engine.dispose()
