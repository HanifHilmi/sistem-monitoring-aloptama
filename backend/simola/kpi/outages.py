"""Outage breakdown (FR-KPI-009): the contiguous intervals a scope lost in a period, and why.

Scopes: ``sla``, ``cdp:<code>``, ``ola`` (every component of every site: the minutes behind OLA and pooled
availability), ``site:<slug>`` (all its components) and ``component:<slug>:<type>``.

Causes:
    cdp_no_data    SLA: no CDP produced data. CDP: this CDP produced none. Component: there is no record because
                   no CDP produced data in that minute.
    no_record      component: a CDP produced data, but the site has no merged record for that minute.
    field_missing  component: the record exists but a mandatory field is missing (DCP: every field).
    flagged        component: the minute would be valid, but an active manual flag covers it (R2.3, FR-DQ-006).
    detection      component: the minute would be valid, but a confirmed detection on a mandatory field covers it
                   (R2.4, FR-DQ-005).

A minute already lost for another reason keeps that reason, so a flag or detection only adds the minutes it really
cost and no minute is counted twice. Flags come before detections, older before newer (PRD E9).

The intervals cover exactly the minutes the KPI engine counts as missing: the same clipped window (coverage
start, in-service period, now - grace) and the same validity SQL (``engine.component_valid_sql``). For any scope
and period their durations add up to the missing minutes the KPIs and the matrix show. For a site (or ``ola``)
that is the sum over its components, so intervals of different components may overlap in time; identical ones
(both CDPs stopping hits every component at once) are listed once, with the components they hit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import intersect, merge_spans, minutes_between
from simola.kpi import engine
from simola.kpi.minutes import parse_scope as parse_minute_scope
from simola.registry import Component, Site, System

logger = logging.getLogger(__name__)

CAUSES = ("cdp_no_data", "no_record", "field_missing", "flagged", "detection")

Span = tuple[datetime, datetime]  # half-open [start, end), minute-aligned


@dataclass(frozen=True)
class Outage:
    start: datetime
    end: datetime
    cause: str
    site: str | None = None
    component: str | None = None
    fields: tuple[str, ...] = ()  # field_missing: the mandatory fields missing during the interval
    flag: int | None = None  # flagged: the flag behind the interval
    reason: str | None = None  # flagged: that flag's reason category
    detection: int | None = None  # detection: the confirmed detection behind the interval
    field: str | None = None  # detection: its field
    rule_type: str | None = None  # detection: its rule type

    @property
    def minutes(self) -> int:
        return minutes_between(self.start, self.end)


@dataclass(frozen=True)
class Run:
    """Consecutive minutes of a site's merged records with the same invalid components and missing fields."""

    start: datetime
    end: datetime
    bad: int  # bit i set: the site's i-th component is invalid
    nulls: int  # bit j set: the site's j-th mandatory field is missing


# ---------------------------------------------------------------------------- spans (pure)
def complement(spans: Sequence[Span], window: Span) -> list[Span]:
    """The parts of ``window`` that the sorted, disjoint ``spans`` do not cover."""
    a, b = window
    out: list[Span] = []
    cur = a
    for s, e in spans:
        if s >= b:
            break
        if e <= cur:
            continue
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < b:
        out.append((cur, b))
    return out


def intersect_spans(x: Sequence[Span], y: Sequence[Span]) -> list[Span]:
    """Intersection of two sorted, disjoint span lists."""
    out: list[Span] = []
    i = j = 0
    while i < len(x) and j < len(y):
        s, e = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        if s < e:
            out.append((s, e))
        if x[i][1] <= y[j][1]:
            i += 1
        else:
            j += 1
    return out


def join_adjacent(pieces: Iterable[Outage]) -> list[Outage]:
    """Sorted by start; touching pieces of the same cause and component become one interval."""
    out: list[Outage] = []
    for p in sorted(pieces, key=lambda o: o.start):
        last = out[-1] if out else None
        if (
            last is not None
            and last.end == p.start
            and (last.cause, last.site, last.component, last.flag, last.detection)
            == (p.cause, p.site, p.component, p.flag, p.detection)
        ):
            out[-1] = replace(last, end=p.end, fields=tuple(dict.fromkeys(last.fields + p.fields)))
        else:
            out.append(p)
    return out


# ---------------------------------------------------------------------------- outages per scope (pure)
def down_outages(down: Sequence[Span]) -> list[Outage]:
    """SLA or CDP uptime: every minute without data flow is lost because the CDP(s) produced no data."""
    return [Outage(s, e, "cdp_no_data") for s, e in down]


def component_outages(
    *,
    window: Span,
    present: Sequence[Span],
    runs: Sequence[Run],
    cdp_down: Sequence[Span],
    bit: int,
    fields: Sequence[tuple[int, str]],
    site: str,
    component: str,
) -> list[Outage]:
    """One component's lost intervals inside its evaluated window.

    ``present``: spans in which the site has a merged record. ``runs``: runs of records that are invalid for at
    least one component. ``cdp_down``: spans in which no CDP produced data. ``bit``: this component's bit in
    ``Run.bad``. ``fields``: (bit in ``Run.nulls``, code) of this component's mandatory fields.
    """
    a, b = window
    if b <= a:
        return []
    gaps = complement(present, window)
    pieces = [Outage(s, e, "cdp_no_data", site, component) for s, e in intersect_spans(gaps, cdp_down)]
    pieces += [
        Outage(s, e, "no_record", site, component)
        for s, e in intersect_spans(gaps, complement(cdp_down, window))
    ]
    for r in runs:
        if not (r.bad >> bit) & 1:
            continue
        s, e = max(r.start, a), min(r.end, b)
        if s < e:
            missing = tuple(code for fb, code in fields if (r.nulls >> fb) & 1)
            pieces.append(Outage(s, e, "field_missing", site, component, missing))
    order = [code for _, code in fields]
    return [
        replace(o, fields=tuple(f for f in order if f in o.fields)) if o.fields else o
        for o in join_adjacent(pieces)
    ]


def flagged_outages(
    *,
    window: Span,
    lost: Sequence[Outage],
    invalid: Sequence[engine.Invalid],
    site: str,
    component: str,
) -> list[Outage]:
    """The minutes flags and confirmed detections cost a component: inside its window, under one of them, and not
    already ``lost``.

    ``invalid`` comes flags first, oldest first; each minute goes to the first interval that covers it.
    """
    a, b = window
    if b <= a or not invalid:
        return []
    taken = merge_spans((o.start, o.end) for o in lost)
    out: list[Outage] = []
    for iv in invalid:
        span = (max(iv.start, a), min(iv.end, b))
        if span[1] <= span[0]:
            continue
        for s, e in intersect_spans([span], complement(taken, window)):
            if iv.source == "flag":
                out.append(Outage(s, e, "flagged", site, component, flag=iv.source_id, reason=iv.reason))
            else:
                out.append(
                    Outage(
                        s,
                        e,
                        "detection",
                        site,
                        component,
                        detection=iv.source_id,
                        field=iv.field,
                        rule_type=iv.rule_type,
                    )
                )
        taken = merge_spans([*taken, span])
    return join_adjacent(out)


@dataclass(frozen=True)
class Group:
    """Identical intervals (same start, end and cause) of several components, e.g. both CDPs stopping at once."""

    start: datetime
    end: datetime
    cause: str
    members: tuple[Outage, ...]
    flag: int | None = None
    reason: str | None = None
    detection: int | None = None

    @property
    def minutes(self) -> int:
        return minutes_between(self.start, self.end)

    @property
    def lost(self) -> int:
        """Component-minutes lost: the interval's share of the scope's missing minutes."""
        return self.minutes * max(1, len(self.members))


def group(outages: Iterable[Outage]) -> list[Group]:
    """Groups identical intervals, longest first; then the most components; then in time order.

    Members keep the order they came in (registry order), and so do ties (the sort is stable).
    """
    groups: dict[tuple[datetime, datetime, str, int | None, int | None], list[Outage]] = {}
    for o in outages:
        groups.setdefault((o.start, o.end, o.cause, o.flag, o.detection), []).append(o)
    out = [Group(s, e, c, tuple(m), f, m[0].reason, d) for (s, e, c, f, d), m in groups.items()]
    return sorted(out, key=lambda g: (-g.minutes, -len(g.members), g.start))


def by_cause(outages: Iterable[Outage]) -> dict[str, int]:
    totals = dict.fromkeys(CAUSES, 0)
    for o in outages:
        totals[o.cause] += o.minutes
    return totals


# ---------------------------------------------------------------------------- database
async def cdp_up_spans(
    conn: AsyncConnection, cdp_ids: list[int], a: datetime, b: datetime
) -> dict[int, list[Span]]:
    """Per CDP, the runs of consecutive minutes with data flow in [a, b)."""
    rows = (
        await conn.execute(
            text("""
        SELECT cdp_id, min(time), max(time) + interval '1 minute' FROM (
            SELECT cdp_id, time,
                   time - (row_number() OVER (PARTITION BY cdp_id ORDER BY time)) * interval '1 minute' AS k
            FROM cdp_minute_fact
            WHERE cdp_id = ANY(:ids) AND data_flow AND time >= :a AND time < :b
        ) x GROUP BY cdp_id, k ORDER BY cdp_id, 2
    """),
            {"ids": cdp_ids, "a": a, "b": b},
        )
    ).all()
    out: dict[int, list[Span]] = {i: [] for i in cdp_ids}
    for cdp_id, s, e in rows:
        out[cdp_id].append((s, e))
    return out


def site_mandatory_fields(site: Site) -> list[str]:
    """The site's mandatory fields, in component order (bit j of ``Run.nulls`` is the j-th)."""
    return list(dict.fromkeys(f for c in site.components for f in c.mandatory))


async def site_runs(
    conn: AsyncConnection, system: System, site: Site, a: datetime, b: datetime
) -> tuple[list[Span], list[Run]]:
    """Spans with a merged record, and the runs of records invalid for at least one of the site's components.

    The database returns runs, not minutes: a month of a site is ~44,600 rows but usually a few dozen runs.
    """
    comps = site.components
    fields = site_mandatory_fields(site)
    if len(comps) > 62 or len(fields) > 62:
        raise ValueError(f"site {site.slug!r} has too many components or mandatory fields for a bit mask")
    if not comps:
        return [], []
    bad = " | ".join(
        f"((NOT {engine.component_valid_sql(system, c)})::int::bigint << {i})" for i, c in enumerate(comps)
    )
    nulls = (
        " | ".join(f"(({system.column(f)} IS NULL)::int::bigint << {j})" for j, f in enumerate(fields))
        or "0::bigint"
    )
    table = engine.MINUTE_TABLE[system.type_code]
    rows = (
        await conn.execute(
            text(f"""
        WITH r AS MATERIALIZED (
            SELECT time, ({bad}) AS bad, ({nulls}) AS nulls FROM {table}
            WHERE site_id = :site AND time >= :a AND time < :b
        )
        SELECT false, min(time), max(time) + interval '1 minute', 0::bigint, 0::bigint FROM (
            SELECT time, time - (row_number() OVER (ORDER BY time)) * interval '1 minute' AS k FROM r
        ) p GROUP BY k
        UNION ALL
        SELECT true, min(time), max(time) + interval '1 minute', bad, nulls FROM (
            SELECT time, bad, nulls,
                   time - (row_number() OVER (PARTITION BY bad, nulls ORDER BY time)) * interval '1 minute' AS k
            FROM r WHERE bad <> 0
        ) x GROUP BY bad, nulls, k
        ORDER BY 2
    """),
            {"site": site.id, "a": a, "b": b},
        )
    ).all()
    present = [(s, e) for invalid, s, e, _, _ in rows if not invalid]
    runs = [Run(s, e, int(bad_), int(nulls_)) for invalid, s, e, bad_, nulls_ in rows if invalid]
    return present, runs


# ---------------------------------------------------------------------------- scopes and report
@dataclass(frozen=True)
class Scope:
    kind: str  # sla | cdp | ola | site | component
    cdp_id: int | None = None
    components: tuple[Component, ...] = ()


def parse_scope(system: System, scope: str) -> Scope:
    if scope == "ola":
        return Scope("ola", components=tuple(c for s in system.sites for c in s.components))
    if scope.startswith("site:"):
        site = system.site_by_slug(scope[5:])
        if site is None:
            raise ValueError(f"unknown scope {scope!r}")
        return Scope("site", components=site.components)
    kind, target = parse_minute_scope(system, scope)
    if kind == "cdp":
        return Scope("cdp", cdp_id=target.id)
    if kind == "component":
        return Scope("component", components=(target,))
    return Scope("sla")


def scope_counts(system: System, scope: Scope, counts: engine.Counts) -> tuple[int, int]:
    """The scope's (valid, expected) minutes, exactly as the KPIs and the matrix show them."""
    if scope.kind == "sla":
        return counts.get(("sla", system.id))
    if scope.kind == "cdp":
        assert scope.cdp_id is not None
        return counts.get(("cdp_flow", scope.cdp_id))
    v = e = 0
    for comp in scope.components:
        cv, ce = counts.get(("component", comp.id))
        v += cv
        e += ce
    return v, e


async def scope_outages(
    conn: AsyncConnection, system: System, scope: Scope, a: datetime, b: datetime
) -> list[Outage]:
    """Every lost interval of the scope in the already-clipped window [a, b), per component in registry order."""
    if b <= a:
        return []
    all_cdps = [c.id for c in system.cdps]
    if scope.kind in ("sla", "cdp"):
        ids = all_cdps if scope.cdp_id is None else [scope.cdp_id]
        up = await cdp_up_spans(conn, ids, a, b)
        return down_outages(complement(merge_spans(s for i in ids for s in up[i]), (a, b)))

    slugs = {s.id: s.slug for s in system.sites}
    wanted = {c.id for c in scope.components}
    per_site: list[tuple[Site, list[Span], list[Run]]] = []
    for site in system.sites:
        if any(c.id in wanted for c in site.components):
            present, runs = await site_runs(conn, system, site, a, b)
            per_site.append((site, present, runs))

    # Data flow is only needed to explain missing records, and those are rare: look it up only then.
    down: list[Span] = []
    if any(complement(present, (a, b)) for _, present, _ in per_site):
        up = await cdp_up_spans(conn, all_cdps, a, b)
        down = complement(merge_spans(s for spans in up.values() for s in spans), (a, b))

    invalid = await engine.invalid_intervals(conn, (c.id for c in scope.components if not c.is_dcp), a, b)
    out: list[Outage] = []
    for site, present, runs in per_site:
        field_bit = {f: j for j, f in enumerate(site_mandatory_fields(site))}
        for i, comp in enumerate(site.components):
            if comp.id not in wanted:
                continue
            window = intersect((a, b), (comp.in_service_from, comp.in_service_to))
            lost = component_outages(
                window=window,
                present=present,
                runs=runs,
                cdp_down=down,
                bit=i,
                fields=[(field_bit[f], f) for f in comp.mandatory],
                site=slugs[site.id],
                component=comp.type_code,
            )
            flagged = flagged_outages(
                window=window,
                lost=lost,
                invalid=[] if comp.is_dcp else invalid.get(comp.id, []),
                site=slugs[site.id],
                component=comp.type_code,
            )
            out += sorted([*lost, *flagged], key=lambda o: o.start)
    return out


def outage_view(g: Group, ongoing: bool) -> dict[str, Any]:
    view: dict[str, Any] = {
        "start": g.start,
        "end": g.end,
        "minutes": g.minutes,
        "cause": g.cause,
        "lost_minutes": g.lost,
        "ongoing": ongoing,
    }
    if g.flag is not None:
        view["flags"] = [{"id": g.flag, "reason": g.reason}]
    if g.detection is not None:
        first = g.members[0]
        view["detections"] = [{"id": g.detection, "field": first.field, "type": first.rule_type}]
    members = [m for m in g.members if m.component is not None]
    if members:
        view["components"] = [
            {"site": m.site, "component": m.component}
            | ({"fields": list(m.fields)} if g.cause == "field_missing" else {})
            for m in members
        ]
    return view


async def outage_report(
    conn: AsyncConnection,
    system: System,
    scope: str,
    start: datetime,
    end: datetime,
    now: datetime,
    limit: int,
) -> dict[str, Any]:
    """The outage breakdown of a scope and period: the KPI's own figure, minutes by cause, longest intervals.

    ``by_cause`` counts every interval (component-minutes for sites and ``ola``), so it adds up to the scope's
    missing minutes even when ``intervals`` stops at ``limit``. So does the sum of ``lost_minutes``.
    """
    sc = parse_scope(system, scope)
    counts, a, b = await engine.period_counts(conn, system, start, end, now)
    valid, expected = scope_counts(system, sc, counts)
    outages = await scope_outages(conn, system, sc, a, b)
    totals = by_cause(outages)
    groups = group(outages)
    if sum(totals.values()) != expected - valid:
        # Normal only while a reprocessed day's stored daily figures wait for their recompute.
        logger.warning(
            "outage minutes differ from the KPI",
            extra={
                "system": system.code,
                "scope": scope,
                "outages": sum(totals.values()),
                "kpi": expected - valid,
            },
        )
    is_open = end > b
    return {
        "system": system.code,
        "scope": scope,
        "period": {
            "from": start,
            "to": end,
            "evaluated_from": a,
            "evaluated_to": max(a, b),
            "as_of": now,
            "open": is_open,
        },
        "availability": engine.availability(valid, expected),
        "by_cause": totals,
        "intervals_total": len(groups),
        "truncated": len(groups) > limit,
        "intervals": [outage_view(g, is_open and g.end == b) for g in groups[:limit]],
    }
