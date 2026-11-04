"""Availability engine (PRD §7.3, FR-KPI-001..007).

All figures come from minute counts:
- SLA (system availability): minutes where at least one CDP produced data (data flow).
- Per-node uptime: minutes where that CDP produced data.
- Reachability: minutes with a successful probe / minutes with any probe (informational).
- Component availability: minutes where all mandatory fields are valid (DCP: any sensor field valid).

Periods are half-open [start, end), clipped to the system's coverage start and to ``now - grace``.
Complete UTC days come from ``availability_daily`` (maintained by recompute); everything else is computed
live with the same SQL, so both paths give identical numbers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import DAY, day_start, floor_minute, intersect, minutes_between
from simola.registry import Component, System, get_setting

MINUTE_TABLE = {"AWOS_CAT3": "awos_cat3_minute"}

Scope = tuple[str, int]  # (scope_type, scope_id)


@dataclass
class Counts:
    """valid/expected minute counts per scope."""

    data: dict[Scope, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))

    def add(self, scope: Scope, valid: int, expected: int) -> None:
        cell = self.data[scope]
        cell[0] += valid
        cell[1] += expected

    def merge(self, other: Counts) -> None:
        for scope, (v, e) in other.data.items():
            self.add(scope, v, e)

    def get(self, scope: Scope) -> tuple[int, int]:
        v, e = self.data.get(scope, [0, 0])
        return v, e


def pct(valid: int, expected: int) -> float | None:
    """Percentage rounded half-up to 2 decimals; None when nothing was expected (FR-KPI-007)."""
    if expected <= 0:
        return None
    if valid > expected:
        raise AssertionError(f"invalid counts: valid {valid} > expected {expected}")
    value = (Decimal(valid) * 100 / Decimal(expected)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(value)


def ratio_pct(r: Decimal | None) -> float | None:
    if r is None:
        return None
    return float((r * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


async def grace_minutes(conn: AsyncConnection) -> int:
    return int(await get_setting(conn, "grace_minutes", 3))


def evaluation_end(now: datetime, grace: int) -> datetime:
    """Minutes m < floor(now) - G are evaluated (FR-KPI-003)."""
    return floor_minute(now) - timedelta(minutes=grace)


def clip_period(
    system: System, start: datetime, end: datetime, now: datetime, grace: int
) -> tuple[datetime, datetime]:
    a = max(floor_minute(start), floor_minute(system.coverage_start))
    b = min(floor_minute(end), evaluation_end(now, grace))
    return a, b


def _component_window(comp: Component, a: datetime, b: datetime) -> tuple[datetime, datetime]:
    return intersect((a, b), (comp.in_service_from, comp.in_service_to))


def component_condition(system: System, comp: Component, params: dict[str, Any]) -> str:
    """SQL condition for 'component valid' on the merged minute table (PRD §7.3.1)."""
    site = next(s for s in system.sites if s.id == comp.site_id)
    if comp.is_dcp:
        cols = system.site_field_columns(site)
        cond = "(" + " OR ".join(f"{c} IS NOT NULL" for c in cols) + ")" if cols else "false"
    else:
        cond = "(" + " AND ".join(f"{system.column(f)} IS NOT NULL" for f in comp.mandatory) + ")"
    parts = [f"site_id = {int(comp.site_id)}", cond]
    if comp.in_service_from is not None:
        params[f"isf_{comp.id}"] = comp.in_service_from
        parts.append(f"time >= :isf_{comp.id}")
    if comp.in_service_to is not None:
        params[f"ist_{comp.id}"] = comp.in_service_to
        parts.append(f"time < :ist_{comp.id}")
    return " AND ".join(parts)


async def live_counts(conn: AsyncConnection, system: System, a: datetime, b: datetime) -> Counts:
    """Counts for an already-clipped window [a, b)."""
    counts = Counts()
    n = minutes_between(a, b)
    if n <= 0:
        return counts
    cdp_ids = [c.id for c in system.cdps]

    rows = (
        (
            await conn.execute(
                text("""
        SELECT cdp_id,
               count(*) FILTER (WHERE data_flow)                                     AS flow,
               count(*) FILTER (WHERE probes_attempted > 0)                          AS sampled,
               count(*) FILTER (WHERE probes_ok > 0)                                 AS reachable,
               count(*) FILTER (WHERE probes_attempted > 0 AND probe_method = 'legacy-v2') AS legacy
        FROM cdp_minute_fact
        WHERE cdp_id = ANY(:ids) AND time >= :a AND time < :b
        GROUP BY cdp_id
    """),
                {"ids": cdp_ids, "a": a, "b": b},
            )
        )
        .mappings()
        .all()
    )
    by_cdp = {r["cdp_id"]: r for r in rows}
    for node in system.cdps:
        r = by_cdp.get(node.id)
        counts.add(("cdp_flow", node.id), int(r["flow"]) if r else 0, n)
        sampled = int(r["sampled"]) if r else 0
        counts.add(("cdp_reach", node.id), int(r["reachable"]) if r else 0, sampled)
        counts.add(("cdp_legacy", node.id), int(r["legacy"]) if r else 0, n)

    sla_up = (
        await conn.execute(
            text("""
        SELECT count(DISTINCT time) FROM cdp_minute_fact
        WHERE cdp_id = ANY(:ids) AND data_flow AND time >= :a AND time < :b
    """),
            {"ids": cdp_ids, "a": a, "b": b},
        )
    ).scalar_one()
    counts.add(("sla", system.id), int(sla_up), n)

    comps = [c for s in system.sites for c in s.components]
    if comps:
        params: dict[str, Any] = {"a": a, "b": b, "sites": [s.id for s in system.sites]}
        selects = [
            f"count(*) FILTER (WHERE {component_condition(system, c, params)}) AS c{c.id}" for c in comps
        ]
        table = MINUTE_TABLE[system.type_code]
        row = (
            (
                await conn.execute(
                    text(
                        f"SELECT {', '.join(selects)} FROM {table} WHERE site_id = ANY(:sites) AND time >= :a AND time < :b"
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
        for c in comps:
            wa, wb = _component_window(c, a, b)
            counts.add(("component", c.id), int(row[f"c{c.id}"]), minutes_between(wa, wb))
    return counts


# ---------------------------------------------------------------------------- rollups
UPSERT_DAILY = text("""
    INSERT INTO availability_daily (scope_type, scope_id, day, valid, expected, computed_at)
    VALUES (:scope_type, :scope_id, :day, :valid, :expected, now())
    ON CONFLICT (scope_type, scope_id, day) DO UPDATE
       SET valid = EXCLUDED.valid, expected = EXCLUDED.expected, computed_at = now()
""")


async def recompute_days(conn: AsyncConnection, system: System, days: list[date], now: datetime) -> int:
    """Store daily counts for complete days. Returns the number of days stored."""
    grace = await grace_minutes(conn)
    eval_end = evaluation_end(now, grace)
    stored = 0
    for d in sorted(set(days)):
        ds, de = day_start(d), day_start(d) + DAY
        if de > eval_end or de <= system.coverage_start:
            continue
        a = max(ds, floor_minute(system.coverage_start))
        counts = await live_counts(conn, system, a, de)
        params = [
            {"scope_type": st, "scope_id": sid, "day": d, "valid": v, "expected": e}
            for (st, sid), (v, e) in counts.data.items()
        ]
        if params:
            await conn.execute(UPSERT_DAILY, params)
        stored += 1
    return stored


async def _rollup_rows(conn: AsyncConnection, system: System, first: date, last: date) -> dict[date, Counts]:
    scopes = scope_ids(system)
    rows = (
        (
            await conn.execute(
                text("""
        SELECT scope_type, scope_id, day, valid, expected FROM availability_daily
        WHERE day >= :first AND day <= :last
          AND ((scope_type = 'sla' AND scope_id = :sys)
               OR (scope_type IN ('cdp_flow', 'cdp_reach', 'cdp_legacy') AND scope_id = ANY(:cdps))
               OR (scope_type = 'component' AND scope_id = ANY(:comps)))
    """),
                {
                    "first": first,
                    "last": last,
                    "sys": system.id,
                    "cdps": scopes["cdp"],
                    "comps": scopes["component"],
                },
            )
        )
        .mappings()
        .all()
    )
    out: dict[date, Counts] = {}
    for r in rows:
        out.setdefault(r["day"], Counts()).add((r["scope_type"], r["scope_id"]), r["valid"], r["expected"])
    return out


def scope_ids(system: System) -> dict[str, list[int]]:
    return {
        "cdp": [c.id for c in system.cdps],
        "component": [c.id for s in system.sites for c in s.components],
    }


async def daily_counts(
    conn: AsyncConnection, system: System, start: datetime, end: datetime, now: datetime
) -> tuple[dict[date, Counts], datetime, datetime]:
    """Per-UTC-day counts over [start, end) after clipping. Partial days are computed live."""
    grace = await grace_minutes(conn)
    a, b = clip_period(system, start, end, now, grace)
    result: dict[date, Counts] = {}
    if b <= a:
        return result, a, b
    first_day, last_day = a.date(), (b - timedelta(minutes=1)).date()
    stored = await _rollup_rows(conn, system, first_day, last_day)
    missing_full: list[date] = []
    d = first_day
    while d <= last_day:
        ds, de = day_start(d), day_start(d) + DAY
        seg_a, seg_b = max(a, ds), min(b, de)
        full = seg_a == ds and seg_b == de
        if full and d in stored:
            result[d] = stored[d]
        elif full:
            missing_full.append(d)
        else:
            result[d] = await live_counts(conn, system, seg_a, seg_b)
        d += timedelta(days=1)
    for d in missing_full:  # normally empty once rollups are maintained
        result[d] = await live_counts(conn, system, day_start(d), day_start(d) + DAY)
    return result, a, b


async def period_counts(
    conn: AsyncConnection, system: System, start: datetime, end: datetime, now: datetime
) -> tuple[Counts, datetime, datetime]:
    days, a, b = await daily_counts(conn, system, start, end, now)
    total = Counts()
    for c in days.values():
        total.merge(c)
    return total, a, b


# ---------------------------------------------------------------------------- KPI report
def availability(valid: int, expected: int) -> dict[str, Any]:
    return {"valid": valid, "expected": expected, "missing": expected - valid, "pct": pct(valid, expected)}


def site_ratio(system: System, counts: Counts, site_id: int) -> tuple[int, int]:
    site = next(s for s in system.sites if s.id == site_id)
    v = e = 0
    for comp in site.components:
        cv, ce = counts.get(("component", comp.id))
        v += cv
        e += ce
    return v, e


def ola_ratio(system: System, counts: Counts) -> Decimal | None:
    ratios = []
    for s in system.sites:
        v, e = site_ratio(system, counts, s.id)
        if e > 0:
            ratios.append(Decimal(v) / Decimal(e))
    if not ratios:
        return None
    return sum(ratios, Decimal(0)) / Decimal(len(ratios))


def kpi_report(system: System, counts: Counts) -> dict[str, Any]:
    sla_v, sla_e = counts.get(("sla", system.id))
    cdps = []
    for c in system.cdps:
        fv, fe = counts.get(("cdp_flow", c.id))
        rv, re_ = counts.get(("cdp_reach", c.id))
        lv, _ = counts.get(("cdp_legacy", c.id))
        cdps.append(
            {
                "code": c.code,
                "uptime": availability(fv, fe),
                "reachability": {
                    "reachable": rv,
                    "sampled": re_,
                    "pct": pct(rv, re_),
                    "probe_coverage_pct": pct(re_, fe),
                    "legacy_minutes": lv,
                },
            }
        )
    sites = []
    pooled_v = pooled_e = 0
    for s in system.sites:
        comps = []
        for comp in s.components:
            cv, ce = counts.get(("component", comp.id))
            pooled_v += cv
            pooled_e += ce
            comps.append(
                {"type": comp.type_code, "is_dcp": comp.is_dcp, "availability": availability(cv, ce)}
            )
        sv, se = site_ratio(system, counts, s.id)
        sites.append(
            {"code": s.code, "slug": s.slug, "availability": availability(sv, se), "components": comps}
        )
    return {
        "sla": availability(sla_v, sla_e),
        "cdps": cdps,
        "sites": sites,
        "ola": {"pct": ratio_pct(ola_ratio(system, counts))},
        "pooled": availability(pooled_v, pooled_e),
    }
