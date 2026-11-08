"""CSV exports (R3.4: FR-EXP-002/003; docs/design/r3.md §4.5).

Four files, each for Viewers and Admins, each audited when it is asked for:

- ``daily``: valid and expected minutes per UTC day for the system (SLA), each CDP (uptime, reachability), each
  site and each sensor. Summing a month's rows gives the month's figures (U7): the numbers come from
  ``engine.daily_counts``, the same counts every screen adds up.
- ``minutes``: one site, one row per minute: the CDPs that had the minute, then per sensor its status (the minute
  map's letters spelled out) and its merged field values.
- ``alarms``: every change of the AWOS alarm files, filtered like the alarm history.
- ``quality``: active manual flags (one row per flag and sensor) and detections.

Files are UTF-8 with a byte-order mark (Excel reads ° and Indonesian text right), comma-separated, one header row,
ISO-8601 UTC times, "." as the decimal point and units in the headers. Text that a spreadsheet would run as a
formula gets a leading apostrophe; numbers are written as they are. Every row ends with the definitions version
and the time the file was made (FR-KPI-008). Files are written a day at a time, so a 31-day minute file never
sits in memory.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import alarms
from simola.core.timeutil import DAY, MINUTE, day_start, floor_minute, minutes_between
from simola.kpi import definitions
from simola.kpi.engine import (
    MINUTE_TABLE,
    Counts,
    component_condition,
    daily_counts,
    evaluation_end,
    grace_minutes,
    invalid_intervals,
    pct,
    site_ratio,
)
from simola.kpi.minutes import apply_invalid, statuses
from simola.registry import Site, System

Kind = Literal["daily", "minutes", "alarms", "quality"]

BOM = "\ufeff"
TRAILER = ["definitions_version", "generated_at_utc"]
DAILY_HEADER = [
    "date_utc",
    "scope",
    "cdp",
    "site",
    "component",
    "expected_min",
    "valid_min",
    "missing_min",
    "availability_pct",
    "reachable_min",
    "probed_min",
    *TRAILER,
]
ALARM_HEADER = [
    "time_utc",
    "alarm_name",
    "type",
    "change",
    "state",
    "place",
    "site",
    "component",
    "message",
    "cdps",
    *TRAILER,
]
QUALITY_HEADER = [
    "kind",
    "id",
    "site",
    "component",
    "field",
    "start_utc",
    "end_utc",
    "minutes",
    "reason",
    "status",
    "counts",
    "rule_id",
    "rule_version",
    "note",
    "by",
    "at_utc",
    *TRAILER,
]
# The minute map's letters (simola.kpi.minutes), spelled out. A minute under a suspect detection still counts.
MINUTE_STATUS = {
    "v": "valid",
    "s": "valid",
    "f": "field_missing",
    "n": "no_data",
    "g": "flagged",
    "d": "detection",
    "u": "not_counted",
}


# ------------------------------------------------------------------------------------------ cells
def text_cell(value: Any) -> str:
    """Text a spreadsheet will not run as a formula (as the audit export does)."""
    if value is None:
        return ""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def number_cell(value: float | int | None) -> str:
    """Numbers as they are, with "." for decimals: 1013 rather than 1013.0, -1.5 stays -1.5."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value != value or value in (float("inf"), float("-inf")):  # NaN or infinite: no reading
        return ""
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def iso(dt: datetime | None) -> str:
    return "" if dt is None else dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pct_cell(valid: int, expected: int) -> str:
    p = pct(valid, expected)
    return "" if p is None else f"{p:.2f}"


class Lines:
    """Turns rows into CSV text, one row at a time."""

    def __init__(self) -> None:
        self._buf = io.StringIO()
        self._w = csv.writer(self._buf, lineterminator="\r\n")

    def __call__(self, rows: Iterable[Sequence[str]]) -> str:
        for r in rows:
            self._w.writerow(r)
        out = self._buf.getvalue()
        self._buf.seek(0)
        self._buf.truncate()
        return out


@dataclass(frozen=True)
class Stamp:
    """The last two cells of every row."""

    generated_at: datetime
    version: str = definitions.VERSION
    cells: list[str] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", [self.version, iso(self.generated_at)])


# ------------------------------------------------------------------------------------------ file names
def _stamp(d: datetime) -> str:
    d = d.astimezone(UTC)
    return d.strftime("%Y-%m-%dT%H%MZ") if (d.hour or d.minute) else d.strftime("%Y-%m-%d")


def file_name(system: str, kind: Kind, start: datetime, end: datetime, site_code: str | None = None) -> str:
    """``SIMOLA_<system>_<kind>[_<site>]_<first>_<last>.csv``, like the monthly PDF's name. Whole days are named by
    the first and the last day included (the end is exclusive); other bounds by their minute. The Exports page
    shows the same name (frontend/src/utils/exports.ts)."""
    e = end.astimezone(UTC)
    last = e - DAY if not (e.hour or e.minute) else e
    site = f"_{site_code}" if site_code else ""
    return f"SIMOLA_{system}_{kind}{site}_{_stamp(start)}_{_stamp(last)}.csv"


# ------------------------------------------------------------------------------------------ (a) daily
def daily_rows(system: System, day: date, counts: Counts, stamp: Stamp) -> Iterator[list[str]]:
    """The system, its CDPs, then each site followed by its sensors, for one day."""
    d = day.isoformat()

    def row(
        scope: str, cdp: str, site: str, comp: str, v: int, e: int, reach: tuple[int, int] | None = None
    ) -> list[str]:
        return [
            d,
            scope,
            cdp,
            site,
            comp,
            str(e),
            str(v),
            str(e - v),
            pct_cell(v, e),
            str(reach[0]) if reach else "",
            str(reach[1]) if reach else "",
            *stamp.cells,
        ]

    yield row("system", "", "", "", *counts.get(("sla", system.id)))
    for c in system.cdps:
        yield row(
            "cdp", c.code, "", "", *counts.get(("cdp_flow", c.id)), reach=counts.get(("cdp_reach", c.id))
        )
    for s in system.sites:
        yield row("site", "", s.code, "", *site_ratio(system, counts, s.id))
        for comp in s.components:
            yield row("component", "", s.code, comp.type_code, *counts.get(("component", comp.id)))


async def daily_file(
    conn: AsyncConnection, system: System, start: datetime, end: datetime, now: datetime
) -> AsyncIterator[str]:
    lines = Lines()
    stamp = Stamp(now)
    yield BOM + lines([DAILY_HEADER])
    days, _, _ = await daily_counts(conn, system, start, end, now)
    for d in sorted(days):
        yield lines(daily_rows(system, d, days[d], stamp))


# ------------------------------------------------------------------------------------------ (b) 1-minute data
def minute_header(system: System, site: Site) -> list[str]:
    """time_utc, cdps, then per sensor ``TYPE.status`` and ``TYPE.FIELD (unit)``; the Exports page lists the same."""
    out = ["time_utc", "cdps"]
    for comp in site.components:
        out.append(f"{comp.type_code}.status")
        for f in comp.fields:
            unit = system.fields[f].unit if f in system.fields else None
            out.append(f"{comp.type_code}.{f} ({unit})" if unit else f"{comp.type_code}.{f}")
    return out + TRAILER


def minute_rows(
    system: System,
    site: Site,
    a: datetime,
    n: int,
    codes: dict[int, str],
    records: dict[datetime, dict[str, Any]],
    sources: dict[datetime, list[int]],
    stamp: Stamp,
) -> Iterator[list[str]]:
    """Rows for the ``n`` minutes from ``a``; ``codes`` holds each component's minute-map letters for them."""
    cdp_code = {c.id: c.code for c in system.cdps}
    cdp_rank = {c.id: c.preference for c in system.cdps}
    for i in range(n):
        m = a + MINUTE * i
        rec = records.get(m)
        row = [
            iso(m),
            " ".join(
                cdp_code.get(c, str(c))
                for c in sorted(sources.get(m, []), key=lambda c: (cdp_rank.get(c, 99), c))
            ),
        ]
        for comp in site.components:
            row.append(MINUTE_STATUS[codes[comp.id][i]])
            for f in comp.fields:
                mf = system.fields.get(f)
                v = rec.get(mf.column) if rec is not None and mf is not None else None
                row.append(text_cell(v) if mf is not None and mf.is_text else number_cell(v))
        yield row + stamp.cells


async def _minute_chunk(
    conn: AsyncConnection, system: System, site: Site, a: datetime, b: datetime, eval_end: datetime
) -> tuple[dict[int, str], dict[datetime, dict[str, Any]], dict[datetime, list[int]]]:
    """One stretch of a site's minutes: each component's letters, the merged records and the CDPs behind them."""
    params: dict[str, Any] = {"a": a, "b": b}
    columns: list[str] = []
    for comp in site.components:
        for f in comp.fields:
            col = system.fields[f].column if f in system.fields else None
            if col and col not in columns:
                columns.append(col)
    oks = [f"({component_condition(system, c, params)}) AS ok_{c.id}" for c in site.components]
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {', '.join(['time', *columns, *oks])} FROM {MINUTE_TABLE[system.type_code]} "
                    f"WHERE site_id = {int(site.id)} AND time >= :a AND time < :b ORDER BY time"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    records = {r["time"]: dict(r) for r in rows}
    sources = {
        r[0]: list(r[1])
        for r in (
            await conn.execute(
                text(f"""
            SELECT time, array_agg(cdp_id) FROM awos_cat3_source_minute
            WHERE cdp_id = ANY(:cdps) AND site_id = {int(site.id)} AND time >= :a AND time < :b GROUP BY time
        """),
                {"cdps": [c.id for c in system.cdps], "a": a, "b": b},
            )
        ).all()
    }
    invalid = await invalid_intervals(conn, [c.id for c in site.components if not c.is_dcp], a, b)
    n = minutes_between(a, b)
    lo = floor_minute(system.coverage_start)
    present = set(records)
    codes: dict[int, str] = {}
    for comp in site.components:
        evaluable = []
        for i in range(n):
            m = a + MINUTE * i
            ok = lo <= m < eval_end
            ok = ok and (comp.in_service_from is None or m >= comp.in_service_from)
            ok = ok and (comp.in_service_to is None or m < comp.in_service_to)
            evaluable.append(ok)
        valid = {m for m, r in records.items() if r[f"ok_{comp.id}"]}
        letters = statuses(a, evaluable, present, valid)
        if not comp.is_dcp:
            letters, _ = apply_invalid(a, letters, invalid.get(comp.id, []))
        codes[comp.id] = letters
    return codes, records, sources


def minute_span(system: System, start: datetime, end: datetime, now: datetime) -> tuple[datetime, datetime]:
    """Rows run from the period's start (not before the coverage start) up to its end or the current minute."""
    return max(start, floor_minute(system.coverage_start)), min(end, floor_minute(now))


async def minutes_file(
    conn: AsyncConnection, system: System, site: Site, start: datetime, end: datetime, now: datetime
) -> AsyncIterator[str]:
    lines = Lines()
    stamp = Stamp(now)
    yield BOM + lines([minute_header(system, site)])
    eval_end = evaluation_end(now, await grace_minutes(conn))
    a, b = minute_span(system, start, end, now)
    while a < b:
        c = min(b, day_start(a.date()) + DAY)  # a UTC day at a time
        codes, records, sources = await _minute_chunk(conn, system, site, a, c, eval_end)
        yield lines(minute_rows(system, site, a, minutes_between(a, c), codes, records, sources, stamp))
        a = c


# ------------------------------------------------------------------------------------------ (c) alarms
def change_word(active: bool, raised: bool) -> str:
    if not active:
        return "cleared"
    return "raised" if raised else "acknowledged"


def alarm_row(system: System, e: dict[str, Any], stamp: Stamp) -> list[str]:
    site = next((s for s in system.sites if s.id == e["site_id"]), None)
    kind = e["place_kind"]
    return [
        iso(e["time"]),
        text_cell(e["name"]),
        e["type"],
        change_word(e["active"], e["raised"]),
        text_cell(e["state"]),
        kind,
        site.code if site and kind in ("site", "component") else "",
        text_cell(e["component_type"]) if kind == "component" else "",
        text_cell(e["message"]),
        " ".join(alarms.cdp_codes(system, e["cdp_ids"])),
        *stamp.cells,
    ]


async def alarms_file(
    conn: AsyncConnection, system: System, f: alarms.HistoryFilter, now: datetime
) -> AsyncIterator[str]:
    lines = Lines()
    stamp = Stamp(now)
    yield BOM + lines([ALARM_HEADER])
    batch: list[list[str]] = []
    async for e in alarms.all_changes(conn, system, f):
        batch.append(alarm_row(system, e, stamp))
        if len(batch) >= 1000:
            yield lines(batch)
            batch = []
    if batch:
        yield lines(batch)


# ------------------------------------------------------------------------------------------ (d) flags and detections
@dataclass(frozen=True)
class QualityOptions:
    flags: bool = True
    detections: bool = True
    all_detections: bool = False  # also suspect and rejected ones (they never count)


def _component(system: System, component_id: int) -> tuple[str, str]:
    for s in system.sites:
        for c in s.components:
            if c.id == component_id:
                return s.code, c.type_code
    return "", ""


def _minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


async def quality_rows(
    conn: AsyncConnection, system: System, start: datetime, end: datetime, o: QualityOptions, stamp: Stamp
) -> list[list[str]]:
    ids = [c.id for s in system.sites for c in s.components]
    found: list[tuple[datetime, int, int, list[str]]] = []
    if o.flags:
        for r in (
            await conn.execute(
                text("""
            SELECT f.id, x.component_id, f.start_at, f.end_at, f.reason, f.note, f.created_by, f.created_at,
                   EXISTS (SELECT 1 FROM invalid_interval i
                           WHERE i.source = 'flag' AND i.source_id = f.id AND i.component_id = x.component_id)
            FROM flag f JOIN flag_component x ON x.flag_id = f.id
            WHERE f.system_id = :sys AND f.removed_at IS NULL AND f.end_at > :a AND f.start_at < :b
        """),
                {"sys": system.id, "a": start, "b": end},
            )
        ).all():
            fid, cid, a, b, reason, note, by, at, counts = r
            site, comp = _component(system, cid)
            found.append(
                (
                    a,
                    0,
                    fid,
                    [
                        "flag",
                        str(fid),
                        site,
                        comp,
                        "",
                        iso(a),
                        iso(b),
                        str(_minutes(a, b)),
                        reason,
                        "active",
                        number_cell(bool(counts)),
                        "",
                        "",
                        text_cell(note),
                        text_cell(by),
                        iso(at),
                    ],
                )
            )
    if o.detections:
        status = "" if o.all_detections else "AND d.status = 'confirmed'"
        for r in (
            await conn.execute(
                text(f"""
            SELECT d.id, d.component_id, d.field_code, d.start_at, d.end_at, d.type, d.status, d.rule_id,
                   d.rule_version, d.note, d.decided_by, d.decided_at,
                   EXISTS (SELECT 1 FROM invalid_interval i WHERE i.source = 'detection' AND i.source_id = d.id)
            FROM dq_detection d
            WHERE d.component_id = ANY(:ids) AND d.end_at > :a AND d.start_at < :b {status}
        """),
                {"ids": ids, "a": start, "b": end},
            )
        ).all():
            did, cid, fld, a, b, rtype, st, rule, version, note, by, at, counts = r
            site, comp = _component(system, cid)
            found.append(
                (
                    a,
                    1,
                    did,
                    [
                        "detection",
                        str(did),
                        site,
                        comp,
                        text_cell(fld),
                        iso(a),
                        iso(b),
                        str(_minutes(a, b)),
                        rtype,
                        st,
                        number_cell(bool(counts)),
                        str(rule),
                        str(version),
                        text_cell(note),
                        text_cell(by),
                        iso(at),
                    ],
                )
            )
    found.sort(key=lambda x: (x[0], x[1], x[2], x[3][2], x[3][3]))
    return [row + stamp.cells for *_, row in found]


async def quality_file(
    conn: AsyncConnection, system: System, start: datetime, end: datetime, o: QualityOptions, now: datetime
) -> AsyncIterator[str]:
    lines = Lines()
    yield BOM + lines([QUALITY_HEADER])
    yield lines(await quality_rows(conn, system, start, end, o, Stamp(now)))


MAX_SPAN: dict[Kind, timedelta] = {
    "daily": timedelta(days=366),
    "minutes": timedelta(days=31),  # FR-EXP-002
    "alarms": timedelta(days=366),
    "quality": timedelta(days=366),
}
