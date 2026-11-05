"""Shared API dependencies: registry cache, period parsing, problem errors."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import ensure_utc, floor_minute
from simola.registry import System, load_systems

_CACHE: tuple[float, list[System]] | None = None
CACHE_TTL_S = 60.0


PROBLEM = "application/problem+json"


def problem_response(status: int, code: str, title: str, detail: Any = None) -> JSONResponse:
    """RFC 9457 problem+json with a stable ``code`` (NFR-SEC-007)."""
    body: dict[str, Any] = {
        "type": f"urn:simola:error:{code}",
        "title": title,
        "status": status,
        "code": code,
    }
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


class ApiError(HTTPException):
    """Rendered as RFC 9457 problem+json with a stable ``code`` the UI translates."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(status_code=status, detail=detail)
        self.code = code


async def systems(conn: AsyncConnection) -> list[System]:
    global _CACHE
    now = time.monotonic()
    if _CACHE is None or now - _CACHE[0] > CACHE_TTL_S:
        _CACHE = (now, await load_systems(conn))
    return _CACHE[1]


def clear_registry_cache() -> None:
    global _CACHE
    _CACHE = None


async def system_or_404(conn: AsyncConnection, code: str) -> System:
    for s in await systems(conn):
        if s.code == code:
            return s
    raise ApiError(404, "system_not_found", f"unknown system {code!r}")


def parse_instant(value: str, name: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return floor_minute(ensure_utc(dt))
    except ValueError as exc:
        raise ApiError(
            422, "invalid_time", f"{name} must be ISO-8601 with a UTC offset, e.g. 2026-11-01T00:00:00Z"
        ) from exc


def parse_period(from_: str, to: str, *, max_span: timedelta) -> tuple[datetime, datetime]:
    start, end = parse_instant(from_, "from"), parse_instant(to, "to")
    if start >= end:
        raise ApiError(422, "invalid_period", "from must be before to")
    if end - start > max_span:
        raise ApiError(422, "period_too_long", f"period longer than {max_span.days} days")
    return start, end
