"""Async database engine. All sessions run in UTC."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from simola.core.config import get_settings

_engine: AsyncEngine | None = None


def make_engine(url: str, *, pool_size: int = 5, application_name: str = "simola") -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=5,
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
