"""Data-quality summary (FR-DQ-008): what manual flags and confirmed detections cost each sensor in a period.

Built from the outage breakdown over every sensor (``outages.scope_outages`` with the ``ola`` scope), so its
minutes are exactly the "flagged" and "detection" minutes of the outage list: a minute a flag or detection covers
but that was already lost for another reason stays under that reason (R3.3 acceptance).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import minutes_between
from simola.kpi import definitions, engine, outages
from simola.registry import System


async def pending_in_period(conn: AsyncConnection, system: System, start: datetime, end: datetime) -> int:
    """Suspect detections waiting for review that overlap the period."""
    ids = [c.id for s in system.sites for c in s.components]
    return int(
        await conn.scalar(
            text("""
            SELECT count(*) FROM dq_detection
            WHERE status = 'suspect' AND component_id = ANY(:ids) AND start_at < :b AND end_at > :a
        """),
            {"ids": ids, "a": start, "b": end},
        )
        or 0
    )


def _add(
    reasons: dict[tuple[str, str], dict[str, Any]], kind: str, reason: str, minutes: int, ref: int
) -> None:
    r = reasons.setdefault((kind, reason), {"kind": kind, "reason": reason, "minutes": 0, "ids": set()})
    r["minutes"] += minutes
    r["ids"].add(ref)


def _reasons(reasons: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    out = [
        {"kind": r["kind"], "reason": r["reason"], "minutes": r["minutes"], "count": len(r["ids"])}
        for r in reasons.values()
    ]
    return sorted(out, key=lambda r: (-r["minutes"], r["kind"], r["reason"]))


async def summary(
    conn: AsyncConnection, system: System, start: datetime, end: datetime, now: datetime, *, signed_in: bool
) -> dict[str, Any]:
    counts, a, b = await engine.period_counts(conn, system, start, end, now)
    lost = await outages.scope_outages(conn, system, outages.parse_scope(system, "ola"), a, b)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    flags: set[int] = set()
    detections: set[int] = set()
    for o in lost:
        if o.cause not in ("flagged", "detection") or o.site is None or o.component is None:
            continue
        minutes = minutes_between(o.start, o.end)
        row = rows.setdefault(
            (o.site, o.component),
            {
                "flagged_minutes": 0,
                "flags": set(),
                "detection_minutes": 0,
                "detections": set(),
                "reasons": {},
            },
        )
        if o.cause == "flagged" and o.flag is not None:
            row["flagged_minutes"] += minutes
            row["flags"].add(o.flag)
            flags.add(o.flag)
            _add(row["reasons"], "flag", o.reason or "other", minutes, o.flag)
            _add(totals, "flag", o.reason or "other", minutes, o.flag)
        elif o.cause == "detection" and o.detection is not None:
            row["detection_minutes"] += minutes
            row["detections"].add(o.detection)
            detections.add(o.detection)
            _add(row["reasons"], "detection", o.rule_type or "range", minutes, o.detection)
            _add(totals, "detection", o.rule_type or "range", minutes, o.detection)

    order = {
        (s.slug, c.type_code): i
        for i, (s, c) in enumerate((s, c) for s in system.sites for c in s.components)
    }
    comp_id = {(s.slug, c.type_code): c.id for s in system.sites for c in s.components}
    components = [
        {
            "site": site,
            "component": comp,
            "flagged_minutes": r["flagged_minutes"],
            "flags": len(r["flags"]),
            "detection_minutes": r["detection_minutes"],
            "detections": len(r["detections"]),
            "expected": counts.get(("component", comp_id[(site, comp)]))[1],
            "reasons": _reasons(r["reasons"]),
        }
        for (site, comp), r in rows.items()
    ]
    components.sort(
        key=lambda c: (-(c["flagged_minutes"] + c["detection_minutes"]), order[(c["site"], c["component"])])
    )
    return {
        "system": system.code,
        "period": {
            "from": start,
            "to": end,
            "evaluated_from": a,
            "evaluated_to": max(a, b),
            "as_of": now,
            "open": end > b,
        },
        "definitions_version": definitions.VERSION,
        "flagged_minutes": sum(c["flagged_minutes"] for c in components),
        "flags": len(flags),
        "detection_minutes": sum(c["detection_minutes"] for c in components),
        "detections": len(detections),
        # Suspects are for signed-in users only (D7, OPEN-13).
        "pending_suspects": await pending_in_period(conn, system, start, end) if signed_in else None,
        "components": components,
        "reasons": _reasons(totals),
    }
