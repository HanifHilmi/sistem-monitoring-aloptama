"""Shared helpers for integration tests that call the API like a browser (R2)."""

from __future__ import annotations

import itertools
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.api.app import create_app
from simola.auth import passwords

PW = "stasiun-cuaca-2026"
# One address per browser keeps the per-address sign-in limit apart (198.18.0.0/15: benchmarking, RFC 2544).
_addresses = (f"198.18.{n // 250}.{n % 250 + 1}" for n in itertools.count())


class Browser:
    """One browser: its own cookies and address. Writes carry the CSRF header unless told otherwise."""

    def __init__(self, address: str | None = None) -> None:
        self.c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()),
            base_url="https://testserver",
            headers={"cf-connecting-ip": address or next(_addresses)},
        )

    async def __aenter__(self) -> Browser:
        await self.c.get("/api/v1/auth/me")  # picks up the CSRF cookie, like the app on startup
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.c.aclose()

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self.c.get(path, **kw)

    async def send(self, method: str, path: str, json: Any = None, *, csrf: bool = True) -> httpx.Response:
        headers = {"x-csrf-token": self.c.cookies.get("simola_csrf", "")} if csrf else {}
        return await self.c.request(method, path, json=json, headers=headers)

    async def login(self, username: str, password: str = PW) -> httpx.Response:
        return await self.send("POST", "/api/v1/auth/login", {"username": username, "password": password})


async def _add_user(engine: AsyncEngine, username: str, role: str, *, must_change: bool = False) -> int:
    async with engine.begin() as conn:
        return int(
            await conn.scalar(
                text("""
            INSERT INTO app_user (username, display_name, role, password_hash, must_change_password, created_by)
            VALUES (:u, :n, :r, :h, :m, 'test') RETURNING id
        """),
                {
                    "u": username,
                    "n": username.title(),
                    "r": role,
                    "h": passwords.hash_password(PW),
                    "m": must_change,
                },
            )
        )
