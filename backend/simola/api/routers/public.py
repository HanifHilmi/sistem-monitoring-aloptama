"""Public read API (FR-DSH, FR-KPI). Responses never contain infrastructure details (FR-AUTH-006)."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import records
from simola.api.deps import ApiError, parse_period, system_or_404, systems
from simola.api.security import principal
from simola.core.db import connection
from simola.core.timeutil import day_start
from simola.kpi import engine, matrix, minutes, outages, series, status
from simola.registry import System, get_setting

router = APIRouter(prefix="/api/v1", tags=["public"])

MAX_KPI_SPAN = timedelta(days=366 * 10)
# Outages are worked out from the minute data: on staging's real data a month of every site takes ~0.35 s and a
# quarter ~1 s. 93 days covers any quarter; longer periods are explained month by month.
MAX_OUTAGE_SPAN = timedelta(days=93)
MAX_OUTAGES = 500


def _now() -> datetime:
    return datetime.now(UTC)


def _registry_view(system: System) -> dict[str, Any]:
    return {
        "code": system.code,
        "type": system.type_code,
        "kpi_profile": system.kpi_profile,
        "name": {"en": system.name_en, "id": system.name_id},
        "icao": system.icao,
        "coverage_start": system.coverage_start,
        "cdps": [{"code": c.code, "preference": c.preference} for c in system.cdps],
        "sites": [
            {
                "code": s.code,
                "slug": s.slug,
                "station_code": s.station_code,
                "name": {"en": s.name_en, "id": s.name_id},
                "components": [
                    {
                        "type": c.type_code,
                        "is_dcp": c.is_dcp,
                        "name": {"en": c.name_en, "id": c.name_id},
                        "fields": list(c.fields),
                        "mandatory": list(c.mandatory),
                        "in_service_from": c.in_service_from,
                        "in_service_to": c.in_service_to,
                    }
                    for c in s.components
                ],
            }
            for s in system.sites
        ],
        "fields": {
            f.code: {"unit": f.unit, "type": f.value_type, "name": {"en": f.name_en, "id": f.name_id}}
            for f in system.fields.values()
        },
    }


def _public_status(st: dict[str, Any]) -> dict[str, Any]:
    out = dict(st)
    out["ingestion"] = [{k: v for k, v in src.items() if not k.startswith("_")} for src in st["ingestion"]]
    return out


@router.get("/settings/display")
async def display_settings(conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    return {
        "color_thresholds": await get_setting(conn, "color_thresholds", {"good": 99, "warning": 95}),
        "grace_minutes": await engine.grace_minutes(conn),
    }


@router.get("/systems")
async def list_systems(conn: AsyncConnection = Depends(connection)) -> list[dict[str, Any]]:
    now = _now()
    out = []
    for system in await systems(conn):
        today = day_start(now.date())
        month = today.replace(day=1)
        today_counts, *_ = await engine.period_counts(conn, system, today, now, now)
        month_counts, *_ = await engine.period_counts(conn, system, month, now, now)
        st = await status.system_status(conn, system, now)
        out.append(
            {
                **{k: v for k, v in _registry_view(system).items() if k in ("code", "type", "name", "icao")},
                "sla_today": engine.availability(*today_counts.get(("sla", system.id))),
                "sla_month": engine.availability(*month_counts.get(("sla", system.id))),
                "ola_month": {"pct": engine.ratio_pct(engine.ola_ratio(system, month_counts))},
                "problems": len(status.problems_from_status(system, st, now)),
                "last_data_minute": st["last_data_minute"],
            }
        )
    return out


@router.get("/systems/{code}")
async def get_system(code: str, conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    return _registry_view(await system_or_404(conn, code))


@router.get("/systems/{code}/kpis")
async def get_kpis(
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_KPI_SPAN)
    now = _now()
    counts, a, b = await engine.period_counts(conn, system, start, end, now)
    return {
        "system": system.code,
        "period": {
            "from": start,
            "to": end,
            "evaluated_from": a,
            "evaluated_to": max(a, b),
            "as_of": now,
            "open": end > b,
            "coverage_start": system.coverage_start,
        },
        **engine.kpi_report(system, counts),
    }


@router.get("/systems/{code}/status")
async def get_status(code: str, conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    return _public_status(await status.system_status(conn, system, _now()))


@router.get("/systems/{code}/problems")
async def get_problems(
    request: Request, code: str, conn: AsyncConnection = Depends(connection)
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    now = _now()
    st = await status.system_status(conn, system, now)
    problems = status.problems_from_status(system, st, now)
    problems += await records.overdue_problems(conn, system, now.date())  # FR-REG-005: public, minor
    # Suspect detections waiting for review are for signed-in users only (FR-DSH-010, OPEN-13).
    user = await principal(request)
    if user is not None and not user.must_change_password:
        from simola.api.routers.dq import pending_suspects

        n = await pending_suspects(conn, system)
        if n:
            problems.append(
                {
                    "code": "suspects_pending",
                    "severity": "info",
                    "link": "/admin/review" if user.is_admin else f"/systems/{system.code}",
                    "params": {"n": n},
                }
            )
    problems.sort(key=lambda p: status.SEVERITY_ORDER[p["severity"]])
    return {"generated_at": now, "problems": problems}


def _bucket_start(d: date, bucket: str) -> date:
    if bucket == "day":
        return d
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    if bucket == "month":
        return d.replace(day=1)
    if bucket == "quarter":
        return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    return date(d.year, 1, 1)


@router.get("/systems/{code}/history")
async def get_history(
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    bucket: Literal["day", "week", "month", "quarter", "year"] = "day",
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    """SLA and OLA per bucket; every bucket equals the KPI figure for that period (FR-DSH-006)."""
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_KPI_SPAN)
    days, _a, _b = await engine.daily_counts(conn, system, start, end, _now())
    buckets: OrderedDict[date, engine.Counts] = OrderedDict()
    for d in sorted(days):
        buckets.setdefault(_bucket_start(d, bucket), engine.Counts()).merge(days[d])
    rows = []
    for b_start, counts in buckets.items():
        rows.append(
            {
                "start": b_start,
                "sla": engine.availability(*counts.get(("sla", system.id))),
                "ola": {"pct": engine.ratio_pct(engine.ola_ratio(system, counts))},
                "cdps": {c.code: engine.availability(*counts.get(("cdp_flow", c.id))) for c in system.cdps},
            }
        )
    return {"system": system.code, "bucket": bucket, "rows": rows}


@router.get("/systems/{code}/calendar")
async def get_calendar(
    code: str,
    year: int = Query(ge=2000, le=2100),
    metric: str = Query("sla", pattern=r"^(sla|ola|cdp:[A-Za-z0-9_-]+)$"),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    start = datetime(year, 1, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC)
    days, _a, _b = await engine.daily_counts(conn, system, start, end, _now())
    cdp = None
    if metric.startswith("cdp:"):
        cdp = system.cdp_by_code(metric[4:])
        if cdp is None:
            raise ApiError(404, "cdp_not_found", f"unknown CDP {metric[4:]!r}")
    out = []
    for d in sorted(days):
        c = days[d]
        if metric == "sla":
            item = engine.availability(*c.get(("sla", system.id)))
        elif metric == "ola":
            item = {"pct": engine.ratio_pct(engine.ola_ratio(system, c))}
        else:
            assert cdp is not None
            item = engine.availability(*c.get(("cdp_flow", cdp.id)))
        out.append({"day": d, **item})
    return {"system": system.code, "year": year, "metric": metric, "days": out}


@router.get("/systems/{code}/sites/{slug}/components/{component}/series")
async def get_series(
    code: str,
    slug: str,
    component: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    site = system.site_by_slug(slug)
    if site is None:
        raise ApiError(404, "site_not_found", f"unknown site {slug!r}")
    comp = next((c for c in site.components if c.type_code == component), None)
    if comp is None:
        raise ApiError(404, "component_not_found", f"unknown component {component!r} at {slug!r}")
    start, end = parse_period(from_, to, max_span=series.max_series_window() + timedelta(minutes=1))
    data = await series.component_series(conn, system, site, comp, start, end, _now())
    return {
        "system": system.code,
        "site": site.slug,
        "component": comp.type_code,
        "from": start,
        "to": end,
        **data,
    }


@router.get("/systems/{code}/matrix")
async def get_matrix(
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    bucket: Literal["day", "week", "month"] = "day",
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    """Availability per row (SLA, CDPs, OLA, sites, components) and period bucket (performance board)."""
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_KPI_SPAN)
    now = _now()
    days, a, b = await engine.grouped_counts(conn, system, start, end, now, bucket)
    first, last = start.date(), (end - timedelta(minutes=1)).date()
    return {
        "system": system.code,
        "period": {
            "from": start,
            "to": end,
            "evaluated_to": max(a, b),
            "as_of": now,
            "open": end > b,
            "recalculating": await recalculating(conn, system, first, last),
        },
        **matrix.build_matrix(system, days, first, last, bucket),
    }


async def recalculating(
    conn: AsyncConnection, system: System, first: date, last: date
) -> list[dict[str, str]]:
    """Days of the period whose figures a queued or running recompute will still change (FR-KPI-008)."""
    rows = (
        await conn.execute(
            text("""
        SELECT DISTINCT params->>'from', params->>'to' FROM job
        WHERE type = 'recompute' AND status IN ('queued', 'running') AND params->>'system' = :code
          AND params->>'from' <= :last AND params->>'to' >= :first
        ORDER BY 1, 2
    """),
            {"code": system.code, "first": first.isoformat(), "last": last.isoformat()},
        )
    ).all()
    return [{"from": max(f, first.isoformat()), "to": min(t, last.isoformat())} for f, t in rows]


@router.get("/systems/{code}/outages")
async def get_outages(
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    scope: str = Query(
        pattern=r"^(sla|ola|cdp:[A-Za-z0-9_-]+|site:[a-z0-9-]+|component:[a-z0-9-]+:[A-Z0-9]+)$"
    ),
    limit: int = Query(100, ge=1, le=MAX_OUTAGES),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    """Lost intervals of one scope with start, end, duration and cause, longest first (FR-KPI-009).

    ``by_cause`` covers every interval, so it adds up to the scope's missing minutes even when the list is cut
    at ``limit``.
    """
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_OUTAGE_SPAN)
    try:
        return await outages.outage_report(conn, system, scope, start, end, _now(), limit)
    except ValueError as exc:
        raise ApiError(404, "scope_not_found", str(exc)) from exc


@router.get("/systems/{code}/minutes")
async def get_minutes(
    request: Request,
    code: str,
    day: date,
    scope: str = Query(pattern=r"^(sla|cdp:[A-Za-z0-9_-]+|component:[a-z0-9-]+:[A-Z0-9]+)$"),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    """Minute-by-minute status of one scope for one UTC day, with its unavailable intervals (FR-DSH-009)."""
    system = await system_or_404(conn, code)
    try:
        user = await principal(request)
        viewer = user is not None and not user.must_change_password
        return await minutes.minute_status(conn, system, scope, day, _now(), viewer=viewer)
    except ValueError as exc:
        raise ApiError(404, "scope_not_found", str(exc)) from exc
