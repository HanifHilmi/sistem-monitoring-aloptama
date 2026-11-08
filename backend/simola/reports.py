"""METAR/SPECI, MET REPORT/SPECIAL and TAF as the AWOS issued them (R3.2: FR-ING-009, FR-RPT-001…003).

What the files hold (both CDPs, from 24 Dec 2025):

- ``reports/METAR.<YYYYMMDD>.log``, ``METREPORT.<date>.log``, ``TAF.<date>.log``: three header lines, then each
  report with the time it was logged, ``YYYY/MM/DD HH:MM:SS <report>``.
- A METAR or MET REPORT line ends with the AWOS's own notes in brackets after the ``=``: the runway in use ``(04)``
  and, for a SPECI or SPECIAL, why it was sent, e.g. ``(thunderstorm onset)``. They are kept apart from the text.
- A TAF is a bulletin heading line (``FTID32 WIDN 071100``) followed by the report over several lines, up to ``=``.
- Each CDP logs the reports it sends: the same report is usually in both logs up to two minutes apart. Copies with
  the same text from different CDPs within ``MATCH_WINDOW`` are one report. A CDP that logs the same report twice
  sent it twice, and both are kept.

Reports are never decoded (FR-RPT-004): the text is stored and shown exactly as issued.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.registry import Cdp, System

ReportType = Literal["metar", "metreport", "taf"]
TYPES: tuple[ReportType, ...] = ("metar", "metreport", "taf")
FILE_PREFIX: dict[ReportType, str] = {"metar": "METAR", "metreport": "METREPORT", "taf": "TAF"}
MATCH_WINDOW = timedelta(minutes=2)
MAX_TEXT = 4000
LATEST = 6
_LOCK_KEY = 7_316_652_200  # + system id: one writer of a system's reports at a time
_SEP = "\x1f"  # joins a row's notes for the bulk insert

_TS = re.compile(r"^(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2}) (.*)$")
_NOTE = re.compile(r"\(([^()]*)\)")
_RUNWAY = re.compile(r"^\d{2}[LRC]?$")
_BULLETIN = re.compile(r"^[A-Z]{4}\d{2} [A-Z]{4} \d{6}( [A-Z]{3})?$")
_KINDS = ("MET REPORT", "SPECIAL", "METAR", "SPECI", "TAF AMD", "TAF COR", "TAF")


def file_name_for(type_: ReportType, day: date) -> str:
    return f"{FILE_PREFIX[type_]}.{day.strftime('%Y%m%d')}.log"


# ------------------------------------------------------------------------------------------ parsing
@dataclass(frozen=True)
class ReportRow:
    type: ReportType
    kind: str
    logged_at: datetime
    text: str
    notes: tuple[str, ...] = ()
    runway: str | None = None
    bulletin: str | None = None


@dataclass
class ReportParse:
    rows: list[ReportRow] = field(default_factory=list)
    warnings: int = 0  # lines that could not be read, or are before coverage or in the future (E5)


def _is_header(line: str) -> bool:
    return line.startswith(("YYYY/", "Report Started on")) or line.endswith(" Report")


def kind_of(report: str) -> str:
    for k in _KINDS:
        if report == k or report.startswith(k + " "):
            return k
    return report.split(" ", 1)[0][:20] or "?"


def split_notes(rest: str) -> tuple[str, tuple[str, ...], str | None]:
    """The report up to its "=", and the AWOS's notes after it (the runway in use apart)."""
    end = rest.rfind("=")
    if end < 0:
        return rest.strip(), (), None
    notes: list[str] = []
    runway = None
    for n in _NOTE.findall(rest[end + 1 :]):
        n = n.strip()
        if _RUNWAY.match(n):
            runway = n
        elif n:
            notes.append(n)
    return rest[: end + 1].strip(), tuple(notes), runway


def _stamp(m: re.Match[str]) -> datetime | None:
    try:
        y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
        return datetime(y, mo, d, h, mi, sec, tzinfo=UTC)
    except ValueError:
        return None


def parse_text(
    content: str,
    type_: ReportType,
    *,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
) -> ReportParse:
    out = ReportParse()
    lines = content.splitlines(keepends=True)
    # A last line without its line end may still be being written: it is read next time.
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines = lines[:-1]

    def keep(
        at: datetime, report: str, notes: tuple[str, ...], runway: str | None, bulletin: str | None
    ) -> None:
        if not report or len(report) > MAX_TEXT:
            out.warnings += 1
        elif (not_before is not None and at < not_before) or (not_after is not None and at > not_after):
            out.warnings += 1
        else:
            out.rows.append(ReportRow(type_, kind_of(report), at, report, notes, runway, bulletin))

    if type_ != "taf":
        for raw in lines:
            line = raw.strip()
            if not line or _is_header(line):
                continue
            m = _TS.match(line)
            at = _stamp(m) if m else None
            if m is None or at is None:
                out.warnings += 1
                continue
            report, notes, runway = split_notes(m.group(7))
            keep(at, report, notes, runway, None)
        return out

    # TAF: a heading line, then the report over several lines up to "=".
    current: tuple[datetime, str | None, list[str]] | None = None

    def finish() -> None:
        nonlocal current
        if current is not None:
            at, bulletin, body = current
            report, notes, runway = split_notes("\n".join(body))
            keep(at, report, notes, runway, bulletin)
        current = None

    for raw in lines:
        line = raw.rstrip("\r\n").rstrip()
        if not line.strip() or _is_header(line.strip()):
            continue
        m = _TS.match(line)
        if m is None:
            if current is None:
                out.warnings += 1
                continue
            current[2].append(line.strip())
            if "=" in line:
                finish()
            continue
        if current is not None:  # the previous TAF never reached its "=": kept as it is
            out.warnings += 1
            finish()
        at = _stamp(m)
        rest = m.group(7).strip()
        if at is None:
            out.warnings += 1
        elif _BULLETIN.match(rest):
            current = (at, rest, [])
        elif rest.startswith("TAF"):
            current = (at, None, [rest])
            if "=" in rest:
                finish()
        else:
            out.warnings += 1
    # A TAF still without its "=" at the end of the file is being written: read again next time.
    return out


# ------------------------------------------------------------------------------------------ merging the CDPs
@dataclass
class MergedReport:
    logged_at: datetime
    kind: str
    notes: list[str]
    runway: str | None
    bulletin: str | None
    cdp_ids: list[int]


def merge_copies(
    rows: Sequence[tuple[datetime, int, str, Sequence[str], str | None, str | None]],
    preference: dict[int, int],
) -> list[MergedReport]:
    """One report text's lines from every CDP, (logged_at, cdp_id, kind, notes, runway, bulletin), as reports.

    A line joins an earlier report when it comes from a CDP that report does not have yet and is at most
    ``MATCH_WINDOW`` later; otherwise it is a report of its own (the same CDP sent it again)."""
    out: list[MergedReport] = []
    for at, cdp, kind, notes, runway, bulletin in sorted(
        rows, key=lambda r: (r[0], preference.get(r[1], 99))
    ):
        match = next(
            (m for m in reversed(out) if at - m.logged_at <= MATCH_WINDOW and cdp not in m.cdp_ids), None
        )
        if match is not None:
            match.cdp_ids.append(cdp)
        else:
            out.append(MergedReport(at, kind, list(notes), runway, bulletin, [cdp]))
    for m in out:
        m.cdp_ids.sort(key=lambda c: preference.get(c, 99))
    return out


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8"), usedforsecurity=False).hexdigest()


# ------------------------------------------------------------------------------------------ writing
async def store(conn: AsyncConnection, system: System, cdp: Cdp, rows: Sequence[ReportRow]) -> int:
    """Stores one CDP's lines; lines already stored are skipped. Returns how many were new, and rebuilds the reports
    of every text that got a new line."""
    if not rows:
        return 0
    await conn.execute(sql("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY + system.id})
    inserted = (
        await conn.execute(
            sql("""
            INSERT INTO report_source_row (system_id, cdp_id, type, kind, logged_at, text, notes, runway, bulletin)
            SELECT CAST(:s AS smallint), CAST(:cdp AS smallint), r.type, r.kind, r.at, r.text,
                   CASE WHEN r.notes = '' THEN '{}'::text[] ELSE string_to_array(r.notes, chr(31)) END,
                   r.runway, r.bulletin
            FROM unnest(CAST(:ty AS text[]), CAST(:k AS text[]), CAST(:t AS timestamptz[]), CAST(:x AS text[]),
                        CAST(:n AS text[]), CAST(:rw AS text[]), CAST(:b AS text[]))
                 AS r(type, kind, at, text, notes, runway, bulletin)
            ON CONFLICT DO NOTHING
            RETURNING type, text
        """),
            {
                "s": system.id,
                "cdp": cdp.id,
                "ty": [r.type for r in rows],
                "k": [r.kind for r in rows],
                "t": [r.logged_at for r in rows],
                "x": [r.text for r in rows],
                "n": [_SEP.join(r.notes) for r in rows],
                "rw": [r.runway for r in rows],
                "b": [r.bulletin for r in rows],
            },
        )
    ).all()
    await rebuild(conn, system, {(r[0], r[1]) for r in inserted})
    return len(inserted)


async def rebuild(conn: AsyncConnection, system: System, keys: Iterable[tuple[str, str]]) -> None:
    """Rebuilds the reports of the given (type, text) from every CDP's lines."""
    keys = sorted(set(keys))
    if not keys:
        return
    params = {"s": system.id, "ty": [k[0] for k in keys], "h": [_md5(k[1]) for k in keys]}
    wanted = "(type, md5(text)) IN (SELECT * FROM unnest(CAST(:ty AS text[]), CAST(:h AS text[])))"
    rows = (
        await conn.execute(
            sql(f"""
            SELECT type, text, logged_at, cdp_id, kind, notes, runway, bulletin FROM report_source_row
            WHERE system_id = :s AND {wanted} ORDER BY logged_at, id
        """),
            params,
        )
    ).all()
    groups: dict[tuple[str, str], list[Any]] = {}
    for r in rows:
        groups.setdefault((r.type, r.text), []).append(r)
    preference = {c.id: c.preference for c in system.cdps}
    entries = []
    for (type_, text_), lines in groups.items():
        for m in merge_copies(
            [(x.logged_at, x.cdp_id, x.kind, x.notes, x.runway, x.bulletin) for x in lines], preference
        ):
            entries.append(
                {
                    "s": system.id,
                    "ty": type_,
                    "k": m.kind,
                    "t": m.logged_at,
                    "x": text_,
                    "n": m.notes,
                    "rw": m.runway,
                    "b": m.bulletin,
                    "c": m.cdp_ids,
                }
            )
    await conn.execute(sql(f"DELETE FROM report_entry WHERE system_id = :s AND {wanted}"), params)
    if entries:
        await conn.execute(
            sql("""
            INSERT INTO report_entry (system_id, type, kind, logged_at, text, notes, runway, bulletin, cdp_ids)
            VALUES (:s, :ty, :k, :t, :x, :n, :rw, :b, :c)
        """),
            entries,
        )


# ------------------------------------------------------------------------------------------ reading
COLUMNS = "id, type, kind, logged_at, text, notes, runway, bulletin, cdp_ids"


def view(system: System, r: Any) -> dict[str, Any]:
    by_id = {c.id: c.code for c in system.cdps}
    return {
        "id": r.id,
        "type": r.type,
        "kind": r.kind,
        "logged_at": r.logged_at,
        "text": r.text,
        "notes": list(r.notes),
        "runway": r.runway,
        "bulletin": r.bulletin,
        "cdps": [by_id.get(c, str(c)) for c in r.cdp_ids],
    }


async def latest(conn: AsyncConnection, system: System) -> dict[str, list[dict[str, Any]]]:
    """FR-RPT-001: the newest reports of each type, newest first."""
    out: dict[str, list[dict[str, Any]]] = {}
    for t in TYPES:
        rows = await conn.execute(
            sql(f"""
            SELECT {COLUMNS} FROM report_entry WHERE system_id = :s AND type = :t
            ORDER BY logged_at DESC, id DESC LIMIT :n
        """),
            {"s": system.id, "t": t, "n": LATEST},
        )
        out[t] = [view(system, r) for r in rows]
    return out


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


async def day(conn: AsyncConnection, system: System, d: date, type_: ReportType) -> dict[str, Any]:
    """FR-RPT-002: one UTC day of one type in the order logged, with each type's count that day."""
    start, end = _day_bounds(d)
    p = {"s": system.id, "a": start, "b": end}
    counts = dict.fromkeys(TYPES, 0)
    for t, n in (
        await conn.execute(
            sql("""
            SELECT type, count(*) FROM report_entry
            WHERE system_id = :s AND logged_at >= :a AND logged_at < :b GROUP BY type
        """),
            p,
        )
    ).all():
        counts[t] = int(n)
    rows = await conn.execute(
        sql(f"""
        SELECT {COLUMNS} FROM report_entry
        WHERE system_id = :s AND type = :t AND logged_at >= :a AND logged_at < :b ORDER BY logged_at, id
    """),
        {**p, "t": type_},
    )
    return {"day": d.isoformat(), "type": type_, "counts": counts, "reports": [view(system, r) for r in rows]}


async def search(
    conn: AsyncConnection,
    system: System,
    type_: ReportType,
    first: date,
    last: date,
    q: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """FR-RPT-003: one type's reports over whole UTC days whose text or AWOS notes hold ``q``, newest first."""
    start, _ = _day_bounds(first)
    _, end = _day_bounds(last)
    where = "system_id = :s AND type = :t AND logged_at >= :a AND logged_at < :b"
    p: dict[str, Any] = {"s": system.id, "t": type_, "a": start, "b": end}
    if q:
        where += " AND (text ILIKE :q OR array_to_string(notes, ' ') ILIKE :q)"
        p["q"] = "%" + re.sub(r"([\\%_])", r"\\\1", q) + "%"
    total = (await conn.execute(sql(f"SELECT count(*) FROM report_entry WHERE {where}"), p)).scalar_one()
    rows = await conn.execute(
        sql(f"""
        SELECT {COLUMNS} FROM report_entry WHERE {where}
        ORDER BY logged_at DESC, id DESC LIMIT :limit OFFSET :offset
    """),
        {**p, "limit": limit, "offset": offset},
    )
    return {"total": int(total), "reports": [view(system, r) for r in rows]}
