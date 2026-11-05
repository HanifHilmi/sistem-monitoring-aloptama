"""Every request looks up its session before it takes a database connection (NFR-PERF-001).

Looked up later, inside a route that already holds a connection, a signed-in page load of ~20 requests could leave
every pooled connection waiting for a second one until the pool timed out (seen on staging, 2026-11-05).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import httpx
import pytest

from tests.permissions import MATRIX, PATH_VALUES


class _NoDatabase:
    async def execute(self, *_: Any, **__: Any) -> Any:
        raise RuntimeError("no database in unit tests")


async def test_the_session_is_looked_up_before_the_request_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    os.environ.setdefault("SIMOLA_DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost:1/unused")
    from simola.api import security
    from simola.api.app import create_app
    from simola.core.db import connection

    order: list[str] = []

    class _Engine:
        @asynccontextmanager
        async def begin(self) -> AsyncIterator[_NoDatabase]:
            order.append("session")
            yield _NoDatabase()

    async def lookup(_conn: object, _token: str | None, _now: datetime) -> None:
        return None

    async def request_connection() -> AsyncIterator[_NoDatabase]:
        order.append("connection")
        yield _NoDatabase()

    monkeypatch.setattr(security, "get_engine", _Engine)
    monkeypatch.setattr(security.sessions, "lookup", lookup)
    app = create_app()
    app.dependency_overrides[connection] = request_connection

    wrong, holding = [], 0
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://testserver", cookies={security.SESSION_COOKIE: "s" * 43}
    ) as client:
        for method, path in sorted(MATRIX):
            if method != "GET" or not path.startswith("/api/"):
                continue
            order.clear()
            await client.get(path.format(**PATH_VALUES))
            holding += "connection" in order
            if order[:1] != ["session"] or order.count("session") != 1:
                wrong.append(f"{path}: {order}")
    assert wrong == [], "the session must be looked up once, before the request's connection"
    assert holding >= 10  # the public routes that hold a connection were all exercised
