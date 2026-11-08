"""METAR/SPECI, MET REPORT/SPECIAL and TAF (R3.2: FR-RPT-001…003). Public, like the reports themselves.

Shown exactly as the AWOS issued them, never decoded (FR-RPT-004). The answers hold only the reports, the AWOS's
notes on them and which CDPs logged them: no addresses or paths (FR-AUTH-006).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import reports
from simola.api.deps import ApiError, system_or_404
from simola.core.db import connection

router = APIRouter(prefix="/api/v1", tags=["reports"])

MAX_SEARCH_DAYS = 31
Type = Literal["metar", "metreport", "taf"]


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


@router.get("/systems/{code}/reports/latest")
async def latest_reports(code: str, conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    return await reports.latest(conn, system)


@router.get("/systems/{code}/reports")
async def report_day(
    code: str,
    day: dt.date,
    type: Type = "metar",
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    if day > _today():
        raise ApiError(422, "future_day", "that day has not come yet")
    return await reports.day(conn, system, day, type)


@router.get("/systems/{code}/reports/search")
async def search_reports(
    code: str,
    from_: dt.date = Query(alias="from"),
    to: dt.date = Query(),
    type: Type = "metar",
    q: str = Query("", max_length=100),
    offset: int = Query(0, ge=0, le=100_000),
    limit: int = Query(50, ge=1, le=200),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    if from_ > to:
        raise ApiError(422, "invalid_period", "from must not be after to")
    if (to - from_).days + 1 > MAX_SEARCH_DAYS:
        raise ApiError(422, "period_too_long", f"period longer than {MAX_SEARCH_DAYS} days")
    return await reports.search(conn, system, type, from_, to, q.strip(), offset=offset, limit=limit)
