"""Detection runs (FR-DQ-003) and the invalidating intervals of confirmed detections (FR-DQ-005).

A run applies every enabled rule to a time range, reading each field's minutes once per site, and merges the hits
into the stored detections (rules.merge). The worker runs the recent minutes after ingestion; a job runs a whole
range month by month after a rule change or a reprocess. The same data and rule versions always give the same
detections; decisions are kept.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import DAY
from simola.dq import rules as R
from simola.kpi.engine import MINUTE_TABLE
from simola.registry import Component, System

SKIP_FIELDS = frozenset({"WGS", "WGD", "RLS"})  # gust events and the light setting are not measurements


def minute_no(t: datetime) -> int:
    return int(t.timestamp() // 60)


def at(m: int) -> datetime:
    return datetime.fromtimestamp(m * 60, UTC)


def _json(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


async def load_rules(conn: AsyncConnection, system: System) -> list[R.RuleRow]:
    """Every rule of the system with its latest version, oldest rule first."""
    rows = (
        await conn.execute(
            text("""
        SELECT r.id, r.component_type_code, r.field_code, r.type, r.proposed,
               v.version, v.site_id, v.params, v.enabled, v.created_by, v.created_at
        FROM dq_rule r
        JOIN LATERAL (SELECT * FROM dq_rule_version x WHERE x.rule_id = r.id ORDER BY x.version DESC LIMIT 1) v
          ON true
        WHERE r.system_id = :sys ORDER BY r.id
    """),
            {"sys": system.id},
        )
    ).all()
    return [
        R.RuleRow(
            int(r[0]), r[1], r[2], r[3], bool(r[4]), int(r[5]), r[6], _json(r[7]), bool(r[8]), r[9], r[10]
        )
        for r in rows
    ]


def checked_fields(system: System, comp: Component) -> list[str]:
    return [
        f for f in comp.fields if f in system.fields and not system.fields[f].is_text and f not in SKIP_FIELDS
    ]


async def field_values(
    conn: AsyncConnection, system: System, site_id: int, field_code: str, a: datetime, b: datetime
) -> tuple[list[int], list[float]]:
    """The field's minutes with a value in [a, b), as minute numbers and values."""
    col = system.column(field_code)
    rows = (
        await conn.execute(
            text(
                f"SELECT (extract(epoch FROM time) / 60)::bigint, {col} FROM {MINUTE_TABLE[system.type_code]} "
                f"WHERE site_id = :s AND time >= :a AND time < :b AND {col} IS NOT NULL ORDER BY time"
            ),
            {"s": site_id, "a": a, "b": b},
        )
    ).all()
    return [int(r[0]) for r in rows], [float(r[1]) for r in rows]


@dataclass
class RunResult:
    raised: int = 0  # new suspects
    changed: int = 0  # extended or merged
    dropped: int = 0  # suspects that no longer hold
    decided_changed: bool = False  # a confirmed detection's stretch moved: figures may follow
    days: set[date] = field(default_factory=set)


async def run(
    conn: AsyncConnection,
    system: System,
    a: datetime,
    b: datetime,
    *,
    rule_ids: Iterable[int] | None = None,
    rules: list[R.RuleRow] | None = None,
) -> RunResult:
    """Applies the enabled rules (or only ``rule_ids``) to [a, b) and stores what changed."""
    all_rules = rules if rules is not None else await load_rules(conn, system)
    only = set(rule_ids) if rule_ids is not None else None
    result = RunResult()
    a_m, b_m = minute_no(a), minute_no(b)
    for site in system.sites:
        for comp in site.components:
            if comp.is_dcp:
                continue
            for f in checked_fields(system, comp):
                chosen = [
                    r
                    for r in R.effective(all_rules, comp.type_code, site.id, f)
                    if only is None or r.id in only
                ]
                if not chosen:
                    continue
                lb = max(R.lookback(r.type, r.params) for r in chosen)
                minutes, values = await field_values(conn, system, site.id, f, at(a_m - lb), b)
                for rule in chosen:
                    hits = [h for h in R.apply(rule.type, rule.params, minutes, values) if h.end > a_m]
                    await _store(conn, rule, comp, f, hits, (a_m, b_m), lb, result)
    if result.decided_changed:
        await sync_invalid(conn, system)
    return result


async def _store(
    conn: AsyncConnection,
    rule: R.RuleRow,
    comp: Component,
    field_code: str,
    hits: list[R.Hit],
    window: tuple[int, int],
    lb: int,
    result: RunResult,
) -> None:
    a_m, b_m = window
    rows = (
        await conn.execute(
            text("""
        SELECT id, start_at, end_at, status, evidence FROM dq_detection
        WHERE rule_id = :r AND rule_version = :v AND component_id = :c AND end_at >= :lo AND start_at <= :hi
        ORDER BY start_at
    """),
            {"r": rule.id, "v": rule.version, "c": comp.id, "lo": at(a_m - lb), "hi": at(b_m)},
        )
    ).all()
    existing = [R.Existing(int(r[0]), minute_no(r[1]), minute_no(r[2]), r[3], _json(r[4])) for r in rows]
    plan = R.merge(rule.type, existing, hits, window)
    by_id = {e.id: e for e in existing}
    if plan.deletes:
        await conn.execute(
            text("DELETE FROM dq_detection WHERE id = ANY(:ids) AND status = 'suspect'"),
            {"ids": sorted(plan.deletes)},
        )
        result.dropped += len(plan.deletes)
    for det_id, h in plan.updates.items():
        await conn.execute(
            text("""
            UPDATE dq_detection SET start_at = :a, end_at = :b, evidence = CAST(:e AS jsonb), updated_at = now()
            WHERE id = :id
        """),
            {"id": det_id, "a": at(h.start), "b": at(h.end), "e": json.dumps(h.evidence)},
        )
        result.changed += 1
        old = by_id[det_id]
        if old.status == "confirmed":
            result.decided_changed = True
            result.days |= _days(min(old.start, h.start), max(old.end, h.end))
    if plan.inserts:
        await conn.execute(
            text("""
            INSERT INTO dq_detection (rule_id, rule_version, component_id, field_code, type, params,
                                      start_at, end_at, evidence)
            VALUES (:r, :v, :c, :f, :t, CAST(:p AS jsonb), :a, :b, CAST(:e AS jsonb))
        """),
            [
                {
                    "r": rule.id,
                    "v": rule.version,
                    "c": comp.id,
                    "f": field_code,
                    "t": rule.type,
                    "p": json.dumps(rule.params),
                    "a": at(h.start),
                    "b": at(h.end),
                    "e": json.dumps(h.evidence),
                }
                for h in plan.inserts
            ],
        )
        result.raised += len(plan.inserts)


def _days(start_m: int, end_m: int) -> set[date]:
    first, last = at(start_m).date(), at(end_m - 1).date()
    return {first + timedelta(days=i) for i in range((last - first).days + 1)}


async def sync_invalid(conn: AsyncConnection, system: System) -> None:
    """Rewrites the invalidating intervals of the system's confirmed detections: one per confirmed detection on a
    field that is mandatory for its component now (FR-DQ-005). DCPs never get one."""
    mandatory = {(c.id, f) for s in system.sites for c in s.components if not c.is_dcp for f in c.mandatory}
    comps = sorted({c.id for s in system.sites for c in s.components})
    await conn.execute(
        text("DELETE FROM invalid_interval WHERE source = 'detection' AND component_id = ANY(:c)"),
        {"c": comps},
    )
    rows = (
        await conn.execute(
            text("""
        SELECT id, component_id, field_code, start_at, end_at FROM dq_detection
        WHERE status = 'confirmed' AND component_id = ANY(:c)
    """),
            {"c": comps},
        )
    ).all()
    keep = [
        {"c": r[1], "a": r[3], "b": r[4], "id": r[0]} for r in rows if (int(r[1]), str(r[2])) in mandatory
    ]
    if keep:
        await conn.execute(
            text("""
            INSERT INTO invalid_interval (component_id, during, source, source_id)
            VALUES (:c, tstzrange(:a, :b, '[)'), 'detection', :id)
        """),
            keep,
        )


async def mark_days(conn: AsyncConnection, system: System, days: Iterable[date], today: date) -> None:
    """Asks the worker to recompute these complete days (the rollup queue, as after ingestion)."""
    complete = sorted(
        d
        for d in set(days)
        if d < today and datetime(d.year, d.month, d.day, tzinfo=UTC) + DAY > system.coverage_start
    )
    if complete:
        await conn.execute(
            text("""
            INSERT INTO rollup_dirty (system_id, day) VALUES (:s, :d)
            ON CONFLICT (system_id, day) DO UPDATE SET marked_at = now()
        """),
            [{"s": system.id, "d": d} for d in complete],
        )
