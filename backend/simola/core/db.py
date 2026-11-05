"""Async database engine. All sessions run in UTC."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from simola.core.config import get_settings

_engine: AsyncEngine | None = None


# Connection budget. The database allows 25 connections, 3 of them reserved for its superuser (TimescaleDB's
# tuning for the staging memory limit), so 22 for SIMOLA. Each API process may hold 4 + 1, the worker 5 + 1 plus
# its leader-lock connection: 2 API processes + worker = 17, leaving room for migrate, the CLI and backups.
# More API processes (SIMOLA_API_WORKERS) need a larger max_connections. A request that finds the pool busy
# waits for a free connection instead of failing (load test 2026-11-05: 134 refused connections with 5 + 5).
API_POOL_SIZE = 4
POOL_OVERFLOW = 1


def make_engine(url: str, *, pool_size: int = API_POOL_SIZE, application_name: str = "simola") -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=POOL_OVERFLOW,
        pool_pre_ping=True,
        connect_args={"server_settings": {"TimeZone": "UTC", "application_name": application_name}},
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def set_engine(engine: AsyncEngine | None) -> None:
    """Used by tests and process entrypoints."""
    global _engine
    _engine = engine


async def connection() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency: one read connection per request."""
    async with get_engine().connect() as conn:
        yield conn
