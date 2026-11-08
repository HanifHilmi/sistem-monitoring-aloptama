"""CSV exports (R3.4: FR-EXP-002/003; docs/design/r3.md §4.5).

Viewers and Admins only. Each request is checked (period, site, filters), counted against a per-user limit
(API-10), recorded in the audit log as ``export`` with its parameters, and only then streamed: an error is a JSON
problem, never half a file. The file is written a day at a time on its own connection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import alarms, exports
from simola.api.deps import ApiError, parse_period, system_or_404
from simola.api.routers.alarms import SCOPE, _scope
from simola.api.security import client_ip, require_viewer
from simola.auth import audit
from simola.auth.sessions import Principal
from simola.core.db import get_engine
from simola.registry import System

router = APIRouter(prefix="/api/v1", tags=["exports"])

# API-10: a person gets at most this many files a minute. A month of 1-minute data takes a few seconds to write.
EXPORTS_PER_MINUTE = 10


def _now() -> datetime:
    return datetime.now(UTC)


async def _begin(
    conn: AsyncConnection,
    request: Request,
    user: Principal,
    system: System,
    kind: exports.Kind,
    start: datetime,
    end: datetime,
    options: dict[str, Any],
) -> None:
    """The per-user limit, then the audit entry (FR-EXP-003), in the request's own transaction."""
    recent = await conn.scalar(
        text("""
        SELECT count(*) FROM audit_event
        WHERE action = 'export' AND actor = :u AND time > now() - interval '1 minute'
    """),
        {"u": user.username},
    )
    if int(recent or 0) >= EXPORTS_PER_MINUTE:
        raise ApiError(429, "too_many_exports", f"at most {EXPORTS_PER_MINUTE} files a minute")
    await audit.record(
        conn,
        "export",
        actor=user.username,
        entity_type="export",
        entity_id=kind,
        after={"system": system.code, "from": start, "to": end, **options},
        source_ip=client_ip(request),
    )


def _csv(name: str, body: AsyncIterator[str]) -> StreamingResponse:
    async def encoded() -> AsyncIterator[bytes]:
        async for chunk in body:
            yield chunk.encode("utf-8")

    return StreamingResponse(
        encoded(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


async def _system_period(
    conn: AsyncConnection, code: str, from_: str, to: str, kind: exports.Kind
) -> tuple[System, datetime, datetime]:
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=exports.MAX_SPAN[kind])
    return system, start, end


@router.get("/systems/{code}/exports/daily.csv", response_model=None)
async def daily_csv(
    request: Request,
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    user: Principal = Depends(require_viewer),
) -> StreamingResponse:
    """(a) Valid and expected minutes per UTC day: the system, each CDP, each site and each sensor."""
    now = _now()
    async with get_engine().begin() as conn:
        system, start, end = await _system_period(conn, code, from_, to, "daily")
        await _begin(conn, request, user, system, "daily", start, end, {})

    async def body() -> AsyncIterator[str]:
        async with get_engine().connect() as conn:
            async for chunk in exports.daily_file(conn, system, start, end, now):
                yield chunk

    return _csv(exports.file_name(system.code, "daily", start, end), body())


@router.get("/systems/{code}/exports/minutes.csv", response_model=None)
async def minutes_csv(
    request: Request,
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    site: str = Query(pattern=r"^[a-z0-9-]+$"),
    user: Principal = Depends(require_viewer),
) -> StreamingResponse:
    """(b) One site's merged 1-minute data, up to 31 days (FR-EXP-002)."""
    now = _now()
    async with get_engine().begin() as conn:
        system, start, end = await _system_period(conn, code, from_, to, "minutes")
        place = system.site_by_slug(site)
        if place is None:
            raise ApiError(404, "site_not_found", f"unknown site {site!r}")
        await _begin(conn, request, user, system, "minutes", start, end, {"site": site})

    async def body() -> AsyncIterator[str]:
        async with get_engine().connect() as conn:
            async for chunk in exports.minutes_file(conn, system, place, start, end, now):
                yield chunk

    return _csv(exports.file_name(system.code, "minutes", start, end, place.code), body())


@router.get("/systems/{code}/exports/alarms.csv", response_model=None)
async def alarms_csv(
    request: Request,
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    type: Literal["error", "warning"] | None = None,
    scope: str | None = Query(None, pattern=SCOPE),
    user: Principal = Depends(require_viewer),
) -> StreamingResponse:
    """(c) Every alarm change, filtered like the alarm history."""
    now = _now()
    async with get_engine().begin() as conn:
        system, start, end = await _system_period(conn, code, from_, to, "alarms")
        place = _scope(system, scope)
        options = {k: v for k, v in {"type": type, "scope": place}.items() if v}
        await _begin(conn, request, user, system, "alarms", start, end, options)
    f = alarms.HistoryFilter(start, end, type, place, order="asc")

    async def body() -> AsyncIterator[str]:
        async with get_engine().connect() as conn:
            async for chunk in exports.alarms_file(conn, system, f, now):
                yield chunk

    return _csv(exports.file_name(system.code, "alarms", start, end), body())


@router.get("/systems/{code}/exports/quality.csv", response_model=None)
async def quality_csv(
    request: Request,
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    records: str = Query("flags,detections", pattern=r"^(flags|detections)(,(flags|detections))?$"),
    all_: bool = Query(False, alias="all"),
    user: Principal = Depends(require_viewer),
) -> StreamingResponse:
    """(d) Active manual flags and detections touching the period (confirmed ones, or every one with ``all``)."""
    now = _now()
    kinds = set(records.split(","))
    o = exports.QualityOptions(flags="flags" in kinds, detections="detections" in kinds, all_detections=all_)
    async with get_engine().begin() as conn:
        system, start, end = await _system_period(conn, code, from_, to, "quality")
        await _begin(
            conn, request, user, system, "quality", start, end, {"records": sorted(kinds), "all": all_}
        )

    async def body() -> AsyncIterator[str]:
        async with get_engine().connect() as conn:
            async for chunk in exports.quality_file(conn, system, start, end, o, now):
                yield chunk

    return _csv(exports.file_name(system.code, "quality", start, end), body())
