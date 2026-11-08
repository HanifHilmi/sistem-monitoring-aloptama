"""AWOS alarms (R3.1: FR-ING-008, FR-ALM-001…004, FR-DSH-010).

What the files hold (both CDPs, 24 Dec 2025 – 6 Nov 2026):

- ``alarm/091ALARM.<YYYYMMDD>.dat``, one per UTC day that had an alarm: a header, then one row per change,
  ``DD/MM/YYYY HH:MM:SS,Site Identifier,Alarm Name,Type,State,Active,Message``. The message may contain commas.
- Each CDP runs its own alarm detection: the same alarm is usually logged by both, up to a minute or two apart.
  Rows of the same name and content within ``MATCH_WINDOW`` of each other, from different CDPs, are one change.
- A raise is logged far more reliably than a clear: an alarm is often raised again with no clear in between, so
  "the latest change says active" does not mean it still is. ``OPEN_HOURS`` decides what counts as active now.

Mapping to sites and sensors is applied when reading, so a change in Admin re-maps the whole history at once.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.registry import Cdp, System

TYPES = ("error", "warning")
MATCH_WINDOW = timedelta(minutes=2)
# An alarm counts as active while its latest change says active and is at most this old. Older ones are listed
# as "no clear logged" and kept out of the Problems panel.
OPEN_HOURS = 24
MAX_MESSAGE = 500
FILE_RE = re.compile(r"ALARM\.(\d{8})\.dat$")
_LOCK_KEY = 7_316_652_100  # + system id: one writer of a system's alarms at a time

PlaceKind = Literal["component", "site", "station", "unmapped"]


def file_name_for(day: date) -> str:
    return f"091ALARM.{day.strftime('%Y%m%d')}.dat"


# ------------------------------------------------------------------------------------------ parsing
@dataclass(frozen=True)
class AlarmRow:
    time: datetime
    name: str
    type: str
    state: str
    active: bool
    message: str


@dataclass
class AlarmParse:
    rows: list[AlarmRow] = field(default_factory=list)
    warnings: int = 0  # rows that could not be read, or are before coverage or in the future (E5)


def parse_text(
    content: str, *, not_before: datetime | None = None, not_after: datetime | None = None
) -> AlarmParse:
    out = AlarmParse()
    seen: set[AlarmRow] = set()
    for raw in content.splitlines():
        line = raw.lstrip("﻿").strip()
        if not line or line.startswith("DD/MM/YYYY"):
            continue
        parts = [p.strip() for p in line.split(",", 6)]
        if len(parts) < 7:
            out.warnings += 1
            continue
        stamp, _site, name, typ, state, active, message = parts
        try:
            t = datetime.strptime(stamp, "%d/%m/%Y %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            out.warnings += 1
            continue
        typ, state, active = typ.lower(), state.lower(), active.lower()
        if (
            typ not in TYPES
            or active not in ("true", "false")
            or not 0 < len(name) <= 200
            or not 0 < len(state) <= 40
            or (not_before is not None and t < not_before)  # e.g. the 1970 rows of a clock reset
            or (not_after is not None and t > not_after)
        ):
            out.warnings += 1
            continue
        row = AlarmRow(t, name, typ, state, active == "true", message[:MAX_MESSAGE])
        if row not in seen:
            seen.add(row)
            out.rows.append(row)
    return out


# ------------------------------------------------------------------------------------------ seed mapping (D4)
# The 75 names seen on the CDPs from 24 Dec 2025 to 6 Nov 2026. They start on the place their name gives; a name
# not on this list arrives "not assigned" (E12) for an Admin to place.
KNOWN_NAMES = frozenset(
    """
    AFTNSerialFailedPortConnectionWarning AFTNSocketFailedPortConnectionWarning BPAIsManualWarning
    BPOutOfRangeWarning DCP6498ApsbDegradedError DCP6498ApsbDegradedWarning DCP6498CpsbDegradedError
    DCP6498CpsbDegradedWarning DCPA_CHIA_DirtyWindowError DCPA_CHIA_DirtyWindowWarning DCPA_CHIA_DoorOpenWarning
    DCPA_CHIA_MissingError DCPA_CHIA_MissingWarning DCPA_Missing DCPA_PWXCommError DCPA_PWXCommWarning
    DCPA_VISA_DataIncompleteError DCPA_VISA_DataIncompleteWarning DCPA_VISA_DataMissingError
    DCPA_VISA_DataMissingWarning DCPA_VISA_DetHead1Error DCPA_VISA_DetHead1Warning DCPA_VISA_DirtyWindowError
    DCPA_VISA_DirtyWindowWarning DCPA_VISA_EmHead0Error DCPA_VISA_EmHead0Warning DCPA_VISA_EmHead1Error
    DCPA_VISA_EmHead1Warning DCPA_VISA_MissingError DCPA_VISA_MissingWarning DCPA_VISA_Pair0DirectError
    DCPA_VISA_Pair0DirectWarning DCPA_VISA_Pair0IndirectError DCPA_VISA_Pair0IndirectWarning
    DCPA_VISA_Pair1DirectError DCPA_VISA_Pair1DirectWarning DCPA_VISA_Pair1IndirectError
    DCPA_VISA_Pair1IndirectWarning DCPA_VISA_ThreeHeadsWarning DCPA_windSensorError DCPA_windSensorWarning
    DCPB_LightningCommError DCPB_LightningCommWarning DCPB_Missing DCPB_windSensorError DCPB_windSensorWarning
    DCPC_CHIC_MissingError DCPC_CHIC_MissingWarning DCPC_Missing DCPC_PWXCommError DCPC_PWXCommWarning
    DCPC_VISC_DataIncompleteError DCPC_VISC_DataIncompleteWarning DCPC_VISC_DataMissingWarning
    DCPC_VISC_DetHead0Error DCPC_VISC_DetHead0Warning DCPC_VISC_DirtyWindowError DCPC_VISC_DirtyWindowWarning
    DCPC_VISC_EmHead0Error DCPC_VISC_EmHead0Warning DCPC_VISC_EmHead1Warning DCPC_VISC_MissingError
    DCPC_VISC_MissingWarning DCPC_VISC_Pair0DirectError DCPC_VISC_Pair0DirectWarning DCPC_VISC_Pair1DirectError
    DCPC_VISC_Pair1DirectWarning DCPC_VISC_Pair1IndirectWarning DCPC_VISC_ThreeHeadsWarning DCPC_windSensorError
    DCPC_windSensorWarning GPSActiveError GPSCommError GPSHWError RLS0_Missing
    """.split()
)
# The letter after "DCP" is the site (PRD): A = Runway 04, B = Middle, C = Runway 22 (station codes).
DCP_LETTER_STATION = {"A": "04", "B": "M", "C": "22"}
_SENSOR_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^DCP([ABC])_Missing$"), "DCP"),
    (re.compile(r"^DCP([ABC])_CHI[ABC]_"), "CEL"),  # ceilometer
    (re.compile(r"^DCP([ABC])_VIS[ABC]_"), "RVR"),  # visibility sensor, part of the RVR system
    (re.compile(r"^DCP([ABC])_PWX"), "PWX"),
    (re.compile(r"^DCP6498([ABC])psb"), "PWX"),  # "Present Weather Sensor … Possible Degraded Performance"
    (re.compile(r"^DCP([ABC])_windSensor"), "ANEM"),
    (re.compile(r"^DCP([ABC])_Lightning"), "LIGH"),
    (re.compile(r"^BP([ABC])IsManual"), "BARO"),  # "BP Sensor at 04 using manually entered value"
)
_STATION_RE = re.compile(r"^(GPS|AFTN|BPOutOfRange)")  # GPS clock, message switch, barometers compared
_SITE_NAMES = {"RLS0_Missing": "04"}  # "RLS Communication Error at Runway 04"


@dataclass(frozen=True)
class Place:
    kind: PlaceKind
    site_id: int | None = None
    component_type: str | None = None


UNMAPPED = Place("unmapped")


def seed_place(system: System, name: str) -> Place:
    """Where a newly seen alarm name starts (D4)."""
    if name not in KNOWN_NAMES:
        return UNMAPPED
    if _STATION_RE.match(name):
        return Place("station")
    if name in _SITE_NAMES:
        site = system.site_by_station(_SITE_NAMES[name])
        return Place("site", site.id) if site else UNMAPPED
    for rx, comp in _SENSOR_RULES:
        m = rx.match(name)
        if m is None:
            continue
        site = system.site_by_station(DCP_LETTER_STATION[m.group(1)])
        if site is None:
            return UNMAPPED
        if any(c.type_code == comp for c in site.components):
            return Place("component", site.id, comp)
        return Place("site", site.id)
    return UNMAPPED


def place_view(system: System, kind: str, site_id: int | None, component: str | None) -> dict[str, Any]:
    site = next((s for s in system.sites if s.id == site_id), None)
    return {"kind": kind, "site": site.slug if site else None, "component": component}


def place_code(p: dict[str, Any]) -> str:
    """ "component:04:RVR", "site:04", "station", "unmapped": as the screens' scope and the audit log say it."""
    if p["kind"] == "component":
        return f"component:{p['site']}:{p['component']}"
    if p["kind"] == "site":
        return f"site:{p['site']}"
    return str(p["kind"])


def in_scope(p: dict[str, Any], scope: str | None) -> bool:
    if not scope:
        return True
    if scope in ("station", "unmapped"):
        return bool(p["kind"] == scope)
    kind, _, rest = scope.partition(":")
    if kind == "site":
        return bool(p["site"] == rest)
    slug, _, comp = rest.partition(":")
    return bool(p["kind"] == "component" and p["site"] == slug and p["component"] == comp)


# ------------------------------------------------------------------------------------------ merging the CDPs
@dataclass
class MergedEvent:
    time: datetime
    type: str
    state: str
    active: bool
    message: str
    cdp_ids: list[int]
    raised: bool = False

    @property
    def key(self) -> tuple[str, str, bool, str]:
        return (self.type, self.state, self.active, self.message)


def merge_rows(
    rows: Sequence[tuple[datetime, int, str, str, bool, str]], preference: dict[int, int]
) -> list[MergedEvent]:
    """One alarm name's rows from every CDP, (time, cdp_id, type, state, active, message), as one list of changes.

    A row joins an earlier change with the same content when it comes from a CDP that change does not have yet and
    is at most ``MATCH_WINDOW`` later. A change "raises" the alarm unless it acknowledges one already active.
    """
    events: list[MergedEvent] = []
    for t, cdp, typ, state, active, message in sorted(rows, key=lambda r: (r[0], preference.get(r[1], 99))):
        key = (typ, state, active, message)
        match = next(
            (
                e
                for e in reversed(events)
                if t - e.time <= MATCH_WINDOW and e.key == key and cdp not in e.cdp_ids
            ),
            None,
        )
        if match is not None:
            match.cdp_ids.append(cdp)
        else:
            events.append(MergedEvent(t, typ, state, active, message, [cdp]))
    was_active = False
    for e in events:
        e.raised = e.active and not (was_active and e.state == "acknowledged")
        e.cdp_ids.sort(key=lambda c: preference.get(c, 99))
        was_active = e.active
    return events


# ------------------------------------------------------------------------------------------ writing
async def store(conn: AsyncConnection, system: System, cdp: Cdp, rows: Sequence[AlarmRow]) -> int:
    """Stores one CDP's rows; rows already stored are skipped. Returns how many were new. Rebuilds the merged
    changes of every name that got a new row."""
    if not rows:
        return 0
    await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY + system.id})
    names = sorted({r.name for r in rows})
    known = {
        n
        for (n,) in (
            await conn.execute(
                text("SELECT name FROM alarm_name WHERE system_id = :s AND name = ANY(:n)"),
                {"s": system.id, "n": names},
            )
        ).all()
    }
    new_names = [n for n in names if n not in known]
    if new_names:
        await conn.execute(
            text("""
            INSERT INTO alarm_name (system_id, name, place_kind, site_id, component_type, source)
            VALUES (:s, :name, :kind, :site, :comp, 'seed') ON CONFLICT DO NOTHING
        """),
            [
                {"s": system.id, "name": n, "kind": p.kind, "site": p.site_id, "comp": p.component_type}
                for n, p in ((n, seed_place(system, n)) for n in new_names)
            ],
        )
    inserted = (
        await conn.execute(
            text("""
            INSERT INTO alarm_source_row (system_id, cdp_id, time, name, type, state, active, message)
            SELECT CAST(:s AS smallint), CAST(:cdp AS smallint), * FROM unnest(CAST(:t AS timestamptz[]), CAST(:n AS text[]), CAST(:ty AS text[]),
                                         CAST(:st AS text[]), CAST(:a AS boolean[]), CAST(:m AS text[]))
            ON CONFLICT DO NOTHING
            RETURNING name
        """),
            {
                "s": system.id,
                "cdp": cdp.id,
                "t": [r.time for r in rows],
                "n": [r.name for r in rows],
                "ty": [r.type for r in rows],
                "st": [r.state for r in rows],
                "a": [r.active for r in rows],
                "m": [r.message for r in rows],
            },
        )
    ).all()
    for name in sorted({r[0] for r in inserted}):
        await rebuild(conn, system, name)
    return len(inserted)


async def rebuild(conn: AsyncConnection, system: System, name: str) -> None:
    rows = (
        await conn.execute(
            text("""
            SELECT time, cdp_id, type, state, active, message FROM alarm_source_row
            WHERE system_id = :s AND name = :n ORDER BY time, id
        """),
            {"s": system.id, "n": name},
        )
    ).all()
    events = merge_rows(
        [(r.time, r.cdp_id, r.type, r.state, r.active, r.message) for r in rows],
        {c.id: c.preference for c in system.cdps},
    )
    await conn.execute(
        text("DELETE FROM alarm_event WHERE system_id = :s AND name = :n"), {"s": system.id, "n": name}
    )
    if events:
        await conn.execute(
            text("""
            INSERT INTO alarm_event (system_id, time, name, type, state, active, raised, message, cdp_ids)
            VALUES (:s, :t, :n, :ty, :st, :a, :r, :m, :c)
        """),
            [
                {
                    "s": system.id,
                    "t": e.time,
                    "n": name,
                    "ty": e.type,
                    "st": e.state,
                    "a": e.active,
                    "r": e.raised,
                    "m": e.message,
                    "c": e.cdp_ids,
                }
                for e in events
            ],
        )


# ------------------------------------------------------------------------------------------ reading
def cdp_codes(system: System, ids: Sequence[int]) -> list[str]:
    by_id = {c.id: c.code for c in system.cdps}
    return [by_id.get(i, str(i)) for i in ids]


LATEST = text("""
    SELECT DISTINCT ON (e.name) e.name, e.type, e.state, e.active, e.message, e.time AS changed, e.cdp_ids,
           (SELECT max(r.time) FROM alarm_event r
             WHERE r.system_id = e.system_id AND r.name = e.name AND r.raised) AS since,
           n.place_kind, n.site_id, n.component_type
    FROM alarm_event e JOIN alarm_name n ON n.system_id = e.system_id AND n.name = e.name
    WHERE e.system_id = :s
    ORDER BY e.name, e.time DESC, e.id DESC
""")


async def current(
    conn: AsyncConnection, system: System, now: datetime, scope: str | None = None
) -> dict[str, Any]:
    """FR-ALM-001. ``active``: the latest change says active and is at most ``OPEN_HOURS`` old, errors first then
    the oldest; ``not_cleared``: the latest change says active but is older, newest first."""
    edge = now - timedelta(hours=OPEN_HOURS)
    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for r in (await conn.execute(LATEST, {"s": system.id})).mappings():
        if not r["active"]:
            continue
        place = place_view(system, r["place_kind"], r["site_id"], r["component_type"])
        if not in_scope(place, scope):
            continue
        item = {
            "name": r["name"],
            "type": r["type"],
            "state": r["state"],
            "message": r["message"],
            "since": r["since"] or r["changed"],
            "changed": r["changed"],
            "cdps": cdp_codes(system, r["cdp_ids"]),
            "place": place,
        }
        (active if r["changed"] >= edge else stale).append(item)
    active.sort(key=lambda a: (a["type"] != "error", a["since"]))
    stale.sort(key=lambda a: (a["type"] != "error", -a["changed"].timestamp()))
    return {"window_hours": OPEN_HOURS, "active": active, "not_cleared": stale}


async def problem(
    conn: AsyncConnection, system: System, now: datetime, *, signed_in: bool
) -> dict[str, Any] | None:
    """The Problems panel item: the number of active alarms for everyone; the list is for signed-in users."""
    active = (await current(conn, system, now))["active"]
    if not active:
        return None
    errors = sum(1 for a in active if a["type"] == "error")
    return {
        "code": "alarms_active",
        "severity": "minor" if errors else "info",
        "link": f"/systems/{system.code}/alarms" if signed_in else f"/systems/{system.code}",
        "params": {"n": len(active), "errors": errors},
    }


@dataclass
class HistoryFilter:
    start: datetime
    end: datetime
    type: str | None = None
    scope: str | None = None
    search: str | None = None
    active: bool | None = None
    order: Literal["asc", "desc"] = "desc"


def _where(system: System, f: HistoryFilter) -> tuple[str, dict[str, Any]]:
    where = ["e.system_id = :s", "e.time >= :start", "e.time < :end"]
    params: dict[str, Any] = {"s": system.id, "start": f.start, "end": f.end}
    if f.type:
        where.append("e.type = :type")
        params["type"] = f.type
    if f.active is not None:
        where.append("e.active = :active")
        params["active"] = f.active
    if f.search:
        like = "%" + re.sub(r"([\\%_])", r"\\\1", f.search) + "%"
        where.append("(e.name ILIKE :q OR e.message ILIKE :q)")
        params["q"] = like
    if f.scope in ("station", "unmapped"):
        where.append("n.place_kind = :kind")
        params["kind"] = f.scope
    elif f.scope:
        kind, _, rest = f.scope.partition(":")
        slug, _, comp = rest.partition(":")
        site = system.site_by_slug(slug)
        where.append("n.site_id = :site")
        params["site"] = site.id if site else -1
        if kind == "component":
            where.append("n.place_kind = 'component' AND n.component_type = :comp")
            params["comp"] = comp
    return " AND ".join(where), params


async def history(
    conn: AsyncConnection, system: System, f: HistoryFilter, *, offset: int, limit: int
) -> dict[str, Any]:
    """FR-ALM-002: the changes in [start, end), filtered; with the alarms raised per UTC day, by type."""
    where, params = _where(system, f)
    base = (
        f"FROM alarm_event e JOIN alarm_name n ON n.system_id = e.system_id AND n.name = e.name WHERE {where}"
    )
    order = "ASC" if f.order == "asc" else "DESC"
    rows = (
        await conn.execute(
            text(f"""
            SELECT e.id, e.time, e.name, e.type, e.state, e.active, e.raised, e.message, e.cdp_ids,
                   n.place_kind, n.site_id, n.component_type
            {base} ORDER BY e.time {order}, e.id {order} LIMIT :limit OFFSET :offset
        """),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings()
    events = [
        {
            "id": r["id"],
            "time": r["time"],
            "name": r["name"],
            "type": r["type"],
            "state": r["state"],
            "active": r["active"],
            "raised": r["raised"],
            "message": r["message"],
            "cdps": cdp_codes(system, r["cdp_ids"]),
            "place": place_view(system, r["place_kind"], r["site_id"], r["component_type"]),
        }
        for r in rows
    ]
    total = (await conn.execute(text(f"SELECT count(*) {base}"), params)).scalar_one()
    counts = {
        (r[0], r[1]): r[2]
        for r in (
            await conn.execute(
                text(f"""
                SELECT (e.time AT TIME ZONE 'UTC')::date, e.type, count(*) {base} AND e.raised GROUP BY 1, 2
            """),
                params,
            )
        ).all()
    }
    per_day = []
    d = f.start.astimezone(UTC).date()
    while datetime(d.year, d.month, d.day, tzinfo=UTC) < f.end:
        per_day.append(
            {
                "day": d.isoformat(),
                "error": counts.get((d, "error"), 0),
                "warning": counts.get((d, "warning"), 0),
            }
        )
        d += timedelta(days=1)
    return {"total": int(total), "events": events, "per_day": per_day}


async def month_summary(
    conn: AsyncConnection, system: System, start: datetime, end: datetime
) -> dict[str, Any]:
    """The monthly report's alarm page (FR-EXP-001 item 6): the changes logged, the alarms raised by type and per
    UTC day (as the alarm history counts them), and how often each alarm was raised, with its place."""
    f = HistoryFilter(start=start, end=end)
    page = await history(conn, system, f, offset=0, limit=1)
    where, params = _where(system, f)
    rows = (
        await conn.execute(
            text(f"""
            SELECT e.name, e.type, n.place_kind, n.site_id, n.component_type, count(*) AS raised, max(e.time) AS last
            FROM alarm_event e JOIN alarm_name n ON n.system_id = e.system_id AND n.name = e.name
            WHERE {where} AND e.raised
            GROUP BY 1, 2, 3, 4, 5
        """),
            params,
        )
    ).mappings()
    names = [
        {
            "name": r["name"],
            "type": r["type"],
            "place": place_view(system, r["place_kind"], r["site_id"], r["component_type"]),
            "raised": int(r["raised"]),
            "last": r["last"],
        }
        for r in rows
    ]
    raised: dict[str, int] = {}
    for n in names:
        raised[n["type"]] = raised.get(n["type"], 0) + n["raised"]
    return {
        "changes": page["total"],
        "raised": raised,
        "per_day": page["per_day"],
        "names": names,
        "names_total": len({n["name"] for n in names}),
    }


async def all_changes(
    conn: AsyncConnection, system: System, f: HistoryFilter
) -> AsyncIterator[dict[str, Any]]:
    """Every change in [start, end) the filter keeps, oldest first, with its place (the CSV export, R3.4)."""
    where, params = _where(system, f)
    rows = await conn.stream(
        text(f"""
        SELECT e.time, e.name, e.type, e.state, e.active, e.raised, e.message, e.cdp_ids,
               n.place_kind, n.site_id, n.component_type
        FROM alarm_event e JOIN alarm_name n ON n.system_id = e.system_id AND n.name = e.name
        WHERE {where} ORDER BY e.time, e.id
    """),
        params,
    )
    async for r in rows.mappings():
        yield dict(r)


async def names(conn: AsyncConnection, system: System) -> list[dict[str, Any]]:
    """Admin → Alarm mapping: every name seen, with its latest message; not assigned first."""
    rows = (
        await conn.execute(
            text("""
            SELECT n.name, n.place_kind, n.site_id, n.component_type, n.source, n.updated_by, n.updated_at,
                   l.type, l.message, l.time AS last_seen, c.events
            FROM alarm_name n
            JOIN LATERAL (SELECT type, message, time FROM alarm_event e
                          WHERE e.system_id = n.system_id AND e.name = n.name
                          ORDER BY time DESC, id DESC LIMIT 1) l ON true
            JOIN LATERAL (SELECT count(*) AS events FROM alarm_event e
                          WHERE e.system_id = n.system_id AND e.name = n.name) c ON true
            WHERE n.system_id = :s
            ORDER BY n.place_kind <> 'unmapped', n.name
        """),
            {"s": system.id},
        )
    ).mappings()
    return [
        {
            "name": r["name"],
            "type": r["type"],
            "message": r["message"],
            "place": place_view(system, r["place_kind"], r["site_id"], r["component_type"]),
            "source": r["source"],
            "events": int(r["events"]),
            "last_seen": r["last_seen"],
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


class PlaceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_place(system: System, kind: str, site: str | None, component: str | None) -> Place:
    """An Admin's choice as a stored place; refuses a site or sensor the system does not have."""
    if kind in ("station", "unmapped"):
        return Place(kind)  # type: ignore[arg-type]
    st = system.site_by_slug(site or "")
    if st is None:
        raise PlaceError("site_not_found")
    if kind == "site":
        return Place("site", st.id)
    if not any(c.type_code == component for c in st.components):
        raise PlaceError("component_not_found")
    return Place("component", st.id, component)
