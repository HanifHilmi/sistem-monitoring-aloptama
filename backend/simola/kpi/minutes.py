"""Minute-by-minute status for one scope and one UTC day (FR-DSH-009 explainability, FR-KPI-009 outages).

Status codes per minute:
    v  valid (counts as available)
    f  record present but a mandatory field missing (components only)
    n  no record / no data flow
    u  not evaluated: before coverage start, outside the component's in-service period, or not yet due (grace)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import DAY, MINUTE, day_start, floor_minute
from simola.kpi.engine import MINUTE_TABLE, component_condition, evaluation_end, grace_minutes
from simola.registry import Component, System

CAUSE = {"f": "field_missing", "n": "no_data"}


def statuses(
    start: datetime,
    evaluable: list[bool],
    present: set[datetime],
    valid: set[datetime],
) -> str:
    out = []
    for i, ok in enumerate(evaluable):
        m = start + timedelta(minutes=i)
        if not ok:
            out.append("u")
        elif m in valid:
            out.append("v")
        elif m in present:
            out.append("f")
        else:
            out.append("n")
    return "".join(out)


def intervals(start: datetime, codes: str) -> list[dict[str, Any]]:
    """Contiguous runs of unavailable minutes (f/n), longest first."""
    runs: list[dict[str, Any]] = []
    i = 0
    while i < len(codes):
        c = codes[i]
        if c in CAUSE:
            j = i
            while j < len(codes) and codes[j] == c:
                j += 1
            runs.append(
                {
                    "start": start + timedelta(minutes=i),
                    "end": start + timedelta(minutes=j),
                    "minutes": j - i,
                    "cause": CAUSE[c],
                }
            )
            i = j
        else:
            i += 1
    return sorted(runs, key=lambda r: (-r["minutes"], r["start"]))


def parse_scope(system: System, scope: str) -> tuple[str, Any]:
    if scope == "sla":
        return "sla", None
    if scope.startswith("cdp:"):
        cdp = system.cdp_by_code(scope[4:])
        if cdp is not None:
            return "cdp", cdp
    if scope.startswith("component:"):
        parts = scope.split(":")
        if len(parts) == 3:
            site = system.site_by_slug(parts[1])
            comp = next((c for c in site.components if c.type_code == parts[2]), None) if site else None
            if comp is not None:
                return "component", comp
    raise ValueError(f"unknown scope {scope!r}")


async def minute_status(
    conn: AsyncConnection, system: System, scope: str, day: date, now: datetime
) -> dict[str, Any]:
    kind, target = parse_scope(system, scope)
    start, end = day_start(day), day_start(day) + DAY
    eval_end = evaluation_end(now, await grace_minutes(conn))
    lo = floor_minute(system.coverage_start)
    in_from: datetime | None = None
    in_to: datetime | None = None
    if kind == "component":
        in_from, in_to = target.in_service_from, target.in_service_to
    evaluable = []
    for i in range(1440):
        m = start + MINUTE * i
        ok = lo <= m < eval_end
        ok = ok and (in_from is None or m >= in_from) and (in_to is None or m < in_to)
        evaluable.append(ok)

    params: dict[str, Any] = {"a": start, "b": end}
    present: set[datetime] = set()
    valid: set[datetime] = set()
    if kind in ("sla", "cdp"):
        ids = [c.id for c in system.cdps] if kind == "sla" else [target.id]
        rows = (
            await conn.execute(
                text(
                    "SELECT DISTINCT time FROM cdp_minute_fact WHERE cdp_id = ANY(:ids) AND data_flow "
                    "AND time >= :a AND time < :b"
                ),
                {**params, "ids": ids},
            )
        ).all()
        valid = {r[0] for r in rows}
        present = set(valid)
    else:
        comp: Component = target
        cond = component_condition(system, comp, params)
        rows = (
            await conn.execute(
                text(
                    f"SELECT time, ({cond}) AS ok FROM {MINUTE_TABLE[system.type_code]} "
                    f"WHERE site_id = {int(comp.site_id)} AND time >= :a AND time < :b"
                ),
                params,
            )
        ).all()
        present = {r[0] for r in rows}
        valid = {r[0] for r in rows if r[1]}

    codes = statuses(start, evaluable, present, valid)
    expected = sum(1 for c in codes if c != "u")
    valid_minutes = codes.count("v")
    return {
        "scope": scope,
        "day": day,
        "codes": codes,
        "valid": valid_minutes,
        "expected": expected,
        "intervals": intervals(start, codes),
    }
