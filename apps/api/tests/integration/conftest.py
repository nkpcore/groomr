"""PostgreSQL + PostGIS integration fixtures with explicit skip when DB is unavailable."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from chair_api.core.config import get_settings

_MIGRATED = False


@pytest.fixture
async def postgres_test_engine() -> AsyncIterator[AsyncEngine]:
    """Connect to TEST_DATABASE_URL and run Alembic migrations, or skip cleanly if unreachable."""
    global _MIGRATED
    settings = get_settings()
    test_url = settings.test_database_url
    engine = create_async_engine(test_url, pool_pre_ping=True)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.execute(text("SELECT PostGIS_Version()"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(
            f"PostgreSQL + PostGIS unavailable at TEST_DATABASE_URL ({type(exc).__name__})."
        )

    if not _MIGRATED:
        sync_url = test_url.replace("+asyncpg", "+psycopg", 1)
        env = {**os.environ, "DATABASE_URL": test_url}
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            await engine.dispose()
            pytest.fail(f"Alembic upgrade failed for {sync_url}:\n{proc.stderr}")
        _MIGRATED = True

    try:
        yield engine
    finally:
        await engine.dispose()
