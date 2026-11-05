"""What a field's history looks like, and the rule values proposed from it (OPEN-08, FR-DQ-001).

The statistics cover every stored minute of every site whose component of the type reports the field (on staging
about 1.4 million minutes, ~7 s), so they are stored per field and refreshed when older than a week.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.kpi.engine import MINUTE_TABLE
from simola.registry import System

MAX_AGE = timedelta(days=7)
# Slow-changing measurements get a spike rule; direction wraps around and rain or light jump by nature.
SPIKE_FIELDS = frozenset({"TEMP", "DEWP", "RH", "QNH", "DA"})


def sites_reporting(system: System, component_type: str, field_code: str) -> list[int]:
    return [
        s.id
        for s in system.sites
        for c in s.components
        if c.type_code == component_type and field_code in c.fields and not c.is_dcp
    ]


async def compute(
    conn: AsyncConnection, system: System, component_type: str, field_code: str
) -> dict[str, Any]:
    """Percentiles of the values, of unchanged runs and of minute-to-minute changes, over the whole history."""
    col = system.column(field_code)
    sites = sites_reporting(system, component_type, field_code)
    row = (
        (
            await conn.execute(
                text(f"""
        WITH v AS MATERIALIZED (
            SELECT site_id, time, {col} AS v FROM {MINUTE_TABLE[system.type_code]}
            WHERE site_id = ANY(:sites) AND {col} IS NOT NULL
        ),
        s AS (
            SELECT abs(v - lag(v) OVER w) AS step, time - lag(time) OVER w AS gap
            FROM v WINDOW w AS (PARTITION BY site_id ORDER BY time)
        ),
        r AS (
            SELECT count(*) AS n FROM (
                SELECT site_id, v,
                       time - (row_number() OVER (PARTITION BY site_id, v ORDER BY time)) * interval '1 minute' AS k
                FROM v
            ) x GROUP BY site_id, v, k
        )
        SELECT (SELECT count(*) FROM v) AS minutes,
               (SELECT min(time) FROM v) AS first, (SELECT max(time) FROM v) AS last,
               (SELECT percentile_disc(ARRAY[0.001, 0.01, 0.999]) WITHIN GROUP (ORDER BY v) FROM v) AS pv,
               (SELECT min(v) FROM v) AS lo, (SELECT max(v) FROM v) AS hi,
               (SELECT max(n) FROM r) AS run_max,
               (SELECT percentile_disc(ARRAY[0.99, 0.999]) WITHIN GROUP (ORDER BY n) FROM r) AS pr,
               (SELECT max(step) FROM s WHERE gap = interval '1 minute') AS step_max,
               (SELECT percentile_disc(ARRAY[0.999, 0.9999]) WITHIN GROUP (ORDER BY step)
                  FROM s WHERE gap = interval '1 minute') AS ps
    """),
                {"sites": sites},
            )
        )
        .mappings()
        .one()
    )
    pv, pr, ps = row["pv"] or [None] * 3, row["pr"] or [None] * 2, row["ps"] or [None] * 2
    return {
        "minutes": int(row["minutes"]),
        "from": row["first"].isoformat() if row["first"] else None,
        "to": row["last"].isoformat() if row["last"] else None,
        "p001": pv[0],
        "p01": pv[1],
        "p999": pv[2],
        "min": row["lo"],
        "max": row["hi"],
        "longest_run_minutes": int(row["run_max"] or 0),
        "run_p99_minutes": int(pr[0] or 0),
        "run_p999_minutes": int(pr[1] or 0),
        "largest_step": round(float(row["step_max"] or 0), 3),
        "step_p999": round(float(ps[0] or 0), 3),
        "step_p9999": round(float(ps[1] or 0), 3),
    }


def _round(v: float, spread: float) -> float:
    digits = 0 if spread >= 50 else 1
    return round(v, digits)


def proposals(field_code: str, unit: str | None, stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Starting values from the history, for the Product Owner to review before any rule is turned on.

    - range: the middle 99.8 % of values widened by a quarter of their spread on each side (never below 0 for a
      field that never goes below 0, never above 100 for a percentage);
    - stuck: twice the 99.9th percentile of unchanged runs, at least an hour, in half hours; values seen in more
      than 1 % of minutes at the bottom of the range (0 for rain or night-time sun) may stay unchanged;
    - spike: twice the 99.99th percentile of minute-to-minute changes (slow-changing fields only).
    """
    out: dict[str, dict[str, Any]] = {}
    lo, hi = stats.get("p001"), stats.get("p999")
    if lo is not None and hi is not None:
        spread = max(float(hi) - float(lo), 1e-9)
        low = float(lo) - spread / 4
        high = float(hi) + spread / 4
        if stats.get("min") is not None and float(stats["min"]) >= 0:
            low = max(0.0, low)
        if unit == "%":
            high = min(100.0, high)
        out["range"] = {"min": _round(low, spread), "max": _round(high, spread)}
    run = max(60, 2 * int(stats.get("run_p999_minutes") or 0))
    stuck: dict[str, Any] = {"minutes": min(1440, int(math.ceil(run / 30) * 30))}
    if stats.get("p01") is not None and stats.get("min") is not None and stats["p01"] == stats["min"]:
        stuck["ignore"] = [stats["min"]]
    out["stuck"] = stuck
    step = float(stats.get("step_p9999") or 0)
    if field_code in SPIKE_FIELDS and step > 0:
        out["spike"] = {"max_change": round(max(2 * step, 0.1), 1)}
    return out


async def field_history(
    conn: AsyncConnection, system: System, component_type: str, field_code: str, *, refresh: bool = False
) -> dict[str, Any]:
    """The stored statistics of a field (worked out and stored when missing or older than a week)."""
    row = (
        await conn.execute(
            text("""
        SELECT stats, computed_at FROM dq_field_history
        WHERE system_id = :s AND component_type_code = :t AND field_code = :f
    """),
            {"s": system.id, "t": component_type, "f": field_code},
        )
    ).first()
    now = datetime.now(UTC)
    if row is not None and not refresh and now - row[1] < MAX_AGE:
        stats = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        computed = row[1]
    else:
        stats = await compute(conn, system, component_type, field_code)
        computed = now
        await conn.execute(
            text("""
            INSERT INTO dq_field_history (system_id, component_type_code, field_code, computed_at, stats)
            VALUES (:s, :t, :f, :at, CAST(:stats AS jsonb))
            ON CONFLICT (system_id, component_type_code, field_code)
            DO UPDATE SET computed_at = EXCLUDED.computed_at, stats = EXCLUDED.stats
        """),
            {"s": system.id, "t": component_type, "f": field_code, "at": now, "stats": json.dumps(stats)},
        )
    unit = system.fields[field_code].unit if field_code in system.fields else None
    return {
        "component_type": component_type,
        "field": field_code,
        "unit": unit,
        "computed_at": computed,
        **stats,
        "proposed": proposals(field_code, unit, stats),
    }


async def propose_rules(
    conn: AsyncConnection, system: System, *, refresh: bool = False
) -> list[dict[str, Any]]:
    """Creates the proposed rules (off, waiting for approval) for every measured field of every component type,
    from its history (OPEN-08). A rule of a kind that already exists for the field is left alone."""
    from simola.auth import audit
    from simola.dq.detect import checked_fields, load_rules

    existing = {
        (r.component_type, r.field, r.type) for r in await load_rules(conn, system) if r.site_id is None
    }
    types: dict[str, set[str]] = {}
    for s in system.sites:
        for c in s.components:
            if not c.is_dcp:
                types.setdefault(c.type_code, set()).update(checked_fields(system, c))
    made: list[dict[str, Any]] = []
    for ctype in sorted(types):
        for f in sorted(types[ctype]):
            hist = await field_history(conn, system, ctype, f, refresh=refresh)
            if not hist.get("minutes"):
                continue
            for rtype, params in hist["proposed"].items():
                if (ctype, f, rtype) in existing:
                    continue
                rule_id = await conn.scalar(
                    text("""
                    INSERT INTO dq_rule (system_id, component_type_code, field_code, type, proposed)
                    VALUES (:s, :t, :f, :ty, true) RETURNING id
                """),
                    {"s": system.id, "t": ctype, "f": f, "ty": rtype},
                )
                await conn.execute(
                    text("""
                    INSERT INTO dq_rule_version (rule_id, version, site_id, params, enabled, created_by)
                    VALUES (:id, 1, NULL, CAST(:p AS jsonb), false, 'system')
                """),
                    {"id": rule_id, "p": json.dumps(params)},
                )
                await audit.record(
                    conn,
                    "rule_created",
                    actor="cli",
                    entity_type="rule",
                    entity_id=f"{rule_id} {ctype}:{f}:{rtype}",
                    after={"site": None, "params": params, "enabled": False, "proposed": True},
                )
                made.append(
                    {"id": rule_id, "component_type": ctype, "field": f, "type": rtype, "params": params}
                )
    return made
