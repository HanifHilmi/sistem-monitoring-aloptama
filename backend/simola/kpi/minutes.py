"""Minute-by-minute status for one scope and one UTC day (FR-DSH-009 explainability, FR-KPI-009 outages).

Status codes per minute:
    v  valid (counts as available)
    f  record present but a mandatory field missing (components only)
    n  no record / no data flow
    g  flagged: the minute would be valid, but an active flag covers it (components only, R2.3). A minute
       already lost for another reason keeps that reason, so it is never counted twice.
    d  confirmed detection: the minute would be valid, but a confirmed detection on a mandatory field covers it
       (R2.4); flags come first.
    s  valid, but a suspect detection covers it: shown to signed-in users only, still counted as valid.
    u  not evaluated: before coverage start, outside the component's in-service period, or not yet due (grace)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import DAY, MINUTE, day_start, floor_minute
from simola.kpi.engine import (
    MINUTE_TABLE,
    Invalid,
    component_condition,
    evaluation_end,
    grace_minutes,
    invalid_intervals,
)
from simola.registry import Component, System

CAUSE = {"f": "field_missing", "n": "no_data", "g": "flagged", "d": "detection"}


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


def _span(start: datetime, a: datetime, b: datetime, n: int) -> range:
    return range(
        max(0, int((a - start).total_seconds()) // 60), min(n, -(-int((b - start).total_seconds()) // 60))
    )


def apply_invalid(start: datetime, codes: str, invalid: Sequence[Invalid]) -> tuple[str, list[int]]:
    """Valid minutes under an invalidating interval become ``g`` (flag) or ``d`` (confirmed detection).

    ``owners[i]`` names what is behind minute i: a flag's id, or minus a detection's id. Intervals come flags
    first, oldest first, so a minute under two of them belongs to the first.
    """
    out = list(codes)
    owners = [0] * len(codes)
    for iv in invalid:
        code, owner = ("g", iv.source_id) if iv.source == "flag" else ("d", -iv.source_id)
        for i in _span(start, iv.start, iv.end, len(out)):
            if out[i] == "v":
                out[i] = code
                owners[i] = owner
    return "".join(out), owners


def apply_suspects(start: datetime, codes: str, suspects: Sequence[tuple[datetime, datetime]]) -> str:
    """Valid minutes under a suspect detection become ``s`` (for signed-in users; still valid)."""
    out = list(codes)
    for a, b in suspects:
        for i in _span(start, a, b, len(out)):
            if out[i] == "v":
                out[i] = "s"
    return "".join(out)


def intervals(
    start: datetime,
    codes: str,
    owners: Sequence[int] | None = None,
    reasons: dict[int, str | None] | None = None,
    detections: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Contiguous runs of unavailable minutes (f/n/g/d), longest first. Flagged runs name their flag, confirmed
    detection runs their detection."""
    runs: list[dict[str, Any]] = []
    own = owners or [0] * len(codes)
    i = 0
    while i < len(codes):
        c = codes[i]
        if c in CAUSE:
            j = i
            while j < len(codes) and codes[j] == c and own[j] == own[i]:
                j += 1
            run: dict[str, Any] = {
                "start": start + timedelta(minutes=i),
                "end": start + timedelta(minutes=j),
                "minutes": j - i,
                "cause": CAUSE[c],
            }
            if c == "g":
                run["flags"] = [{"id": own[i], "reason": (reasons or {}).get(own[i])}]
            if c == "d":
                run["detections"] = [(detections or {}).get(-own[i], {"id": -own[i]})]
            runs.append(run)
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
    conn: AsyncConnection, system: System, scope: str, day: date, now: datetime, *, viewer: bool = False
) -> dict[str, Any]:
    """``viewer``: a signed-in user, who also sees minutes under a suspect detection (``s``)."""
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
    invalid: list[Invalid] = []
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
        if not comp.is_dcp:
            invalid = (await invalid_intervals(conn, [comp.id], start, end)).get(comp.id, [])

    codes, owners = apply_invalid(start, statuses(start, evaluable, present, valid), invalid)
    if viewer and kind == "component" and not target.is_dcp:
        suspects = await conn.execute(
            text("""
            SELECT start_at, end_at FROM dq_detection
            WHERE component_id = :c AND status = 'suspect' AND end_at > :a AND start_at < :b
        """),
            {"c": target.id, "a": start, "b": end},
        )
        codes = apply_suspects(start, codes, [(r[0], r[1]) for r in suspects])
    expected = sum(1 for c in codes if c != "u")
    valid_minutes = codes.count("v") + codes.count("s")
    return {
        "scope": scope,
        "day": day,
        "codes": codes,
        "valid": valid_minutes,
        "expected": expected,
        "intervals": intervals(
            start,
            codes,
            owners,
            {iv.source_id: iv.reason for iv in invalid if iv.source == "flag"},
            {
                iv.source_id: {"id": iv.source_id, "field": iv.field, "type": iv.rule_type}
                for iv in invalid
                if iv.source == "detection"
            },
        ),
    }
