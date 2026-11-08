"""Exports: CSV files (R3.4, FR-EXP-002) and the monthly PDF report (R3.5, FR-EXP-001); docs/design/r3.md §4.4–4.5.

Viewers and Admins only (FR-EXP-003). Each request is checked (period, site, filters), counted against a per-user
limit (API-10), recorded in the audit log as ``export`` with its parameters, and only then sent: an error is a JSON
problem, never half a file. A CSV file is written a day at a time on its own connection. The PDF is drawn one at a
time on the whole server and audited once it is ready.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import alarms, exports
from simola.api.deps import ApiError, parse_period, system_or_404
from simola.api.routers.alarms import SCOPE, _scope
from simola.api.security import client_ip, csrf, require_viewer
from simola.auth import audit
from simola.auth.sessions import Principal
from simola.core.db import get_engine
from simola.core.timeutil import day_start
from simola.registry import System
from simola.report.gather import gather
from simola.report.model import file_name as report_file_name
from simola.report.render import render_pdf

router = APIRouter(prefix="/api/v1", tags=["exports"])

# API-10: a person gets at most this many files a minute. A month of 1-minute data takes a few seconds to write.
EXPORTS_PER_MINUTE = 10


def _now() -> datetime:
    return datetime.now(UTC)


async def _check_limit(conn: AsyncConnection, user: Principal) -> None:
    """API-10: CSV files and monthly reports together, at most EXPORTS_PER_MINUTE a minute per person."""
    recent = await conn.scalar(
        text("""
        SELECT count(*) FROM audit_event
        WHERE action = 'export' AND actor = :u AND time > now() - interval '1 minute'
    """),
        {"u": user.username},
    )
    if int(recent or 0) >= EXPORTS_PER_MINUTE:
        raise ApiError(429, "too_many_exports", f"at most {EXPORTS_PER_MINUTE} files a minute")


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
    await _check_limit(conn, user)
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


# ---------------------------------------------------------------------------- monthly PDF (R3.5)
# One report at a time on the whole server (both API workers): WeasyPrint takes a CPU for a few seconds and the
# host is shared. A Postgres session lock, so a worker that dies mid-report frees it with its connection.
REPORT_LOCK = 0x53494D4F4C41  # "SIMOLA"


class ReportRequest(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="UTC month, YYYY-MM")
    lang: Literal["id", "en"]


@router.post(
    "/systems/{code}/exports/monthly-report",
    response_model=None,
    dependencies=[Depends(csrf)],
    responses={200: {"content": {"application/pdf": {}}}},
)
async def monthly_report(
    request: Request, code: str, body: ReportRequest, user: Principal = Depends(require_viewer)
) -> Response:
    """The monthly PDF report of one UTC month, in Bahasa Indonesia or English (FR-EXP-001)."""
    now = _now()
    month = date.fromisoformat(f"{body.month}-01")
    if day_start(month) > now:
        raise ApiError(422, "month_in_future", "the month has not started yet")
    async with get_engine().connect() as conn:
        system = await system_or_404(conn, code)
        await _check_limit(conn, user)
        await conn.rollback()
        if not await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": REPORT_LOCK}):
            raise ApiError(429, "report_busy", "another report is being drawn; try again in a minute")
        try:
            inputs = await gather(conn, system, month, body.lang, user.display_name, now)
            await conn.rollback()  # no transaction open while the PDF is drawn
            pdf = await asyncio.to_thread(render_pdf, inputs)
            await audit.record(
                conn,
                "export",
                actor=user.username,
                entity_type="export",
                entity_id="monthly-report",
                after={"system": system.code, "month": body.month, "lang": body.lang},
                source_ip=client_ip(request),
            )
            await conn.commit()
        finally:
            await conn.rollback()
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": REPORT_LOCK})
            await conn.commit()
    name = report_file_name(system.code, month, body.lang)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )
