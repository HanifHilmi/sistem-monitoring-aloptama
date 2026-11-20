"""Station, site and sensor records, sensor parts, calibration status and the figure change trace (R2.5, R3.7).

PRD FR-REG-004 (records; a sensor's parts with their own part and serial numbers, hidden from the public),
FR-REG-005 (calibration history and a status derived on read: OK, due soon, overdue, unknown), FR-AUD-003 (which
changes moved a component's figures). Parts never change a figure.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.auth import audit
from simola.registry import Component, System, get_setting

STATION_FIELDS = ("wmo_number", "airport_name", "lat", "lon", "elevation_m", "procurement_year", "notes")
SITE_FIELDS = ("lat", "lon", "elevation_m", "threshold_elevation_m", "description")
# The sensor as a whole. Its models and numbers belong to its parts (R3.7); the older columns on ``component`` are
# kept for one release only (migration 0012) and no longer read.
COMPONENT_FIELDS = ("sensor_type", "installed_on", "notes")
PART_FIELDS = (
    "role",
    "manufacturer",
    "model",
    "part_number",
    "serial_number",
    "firmware",
    "installed_on",
    "notes",
)
PRIVATE_FIELDS = ("part_number", "serial_number")  # signed-in users only (PRD §5.4, OPEN-13)
# Left out of the public answer as well: who changed a part, and free-text notes (like flag notes, PRD §5.4).
PART_SIGNED_IN = (
    *PRIVATE_FIELDS,
    "notes",
    "removed_reason",
    "created_by",
    "created_at",
    "updated_by",
    "updated_at",
)
PART_COLUMNS = (
    "p.id, p.component_id, p.role, p.manufacturer, p.model, p.part_number, p.serial_number, p.firmware, "
    "p.installed_on, p.removed_on, p.removed_reason, p.replaces, p.notes, p.created_by, p.created_at, "
    "p.updated_by, p.updated_at, n.id AS replaced_by"
)
# The part each sensor's existing record became (migration 0012), and what the import calls the main part.
MAIN_PART = {
    "DCP": "Data logger",
    "ATRH": "Thermohygrometer",
    "BARO": "Barometer",
    "ANEM": "Wind sensor",
    "RVR": "Visibility sensor",
    "CEL": "Ceilometer",
    "PWX": "Present weather sensor",
    "RAIN": "Rain gauge",
    "SOLR": "Pyranometer",
    "LIGH": "Lightning detector",
}
DEFAULT_DUE_SOON_DAYS = 30
CALIBRATION_COLUMNS = (
    "cr.id, cr.component_id, cr.date, cr.performed_by, cr.certificate, cr.next_due, cr.interval_months, "
    "cr.validated_on, cr.notes, cr.part_id, cr.created_by, cr.created_at, cr.updated_by, cr.updated_at, "
    "cp.role AS part_role, cp.serial_number AS part_serial"
)
CALIBRATION_FROM = "calibration_record cr LEFT JOIN component_part cp ON cp.id = cr.part_id"
CALIBRATION_AUDIT = (
    "date",
    "performed_by",
    "certificate",
    "next_due",
    "interval_months",
    "validated_on",
    "notes",
    "part_id",
)


class RecordError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------- pure rules
def add_months(d: date, months: int) -> date:
    """The same day ``months`` later, or the month's last day when it has fewer days (31 Jan + 1 → 28/29 Feb)."""
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def calibration_status(
    next_due: date | None, last: date | None, today: date, window: int, validated_on: date | None = None
) -> dict[str, Any]:
    """FR-REG-005: overdue once the due date has passed, due soon within ``window`` days, otherwise OK; unknown
    without a record. Dates are UTC. ``pending``: the latest calibration was done but its certificate is not
    validated yet (it does not change the status)."""
    if next_due is None:
        return {
            "status": "unknown",
            "last": None,
            "next_due": None,
            "days_left": None,
            "validated_on": None,
            "pending": False,
        }
    left = (next_due - today).days
    status = "overdue" if left < 0 else "due_soon" if left <= window else "ok"
    return {
        "status": status,
        "last": last,
        "next_due": next_due,
        "days_left": left,
        "validated_on": validated_on,
        "pending": validated_on is None,
    }


def check_calibration(
    when: date,
    performed_by: str | None,
    next_due: date | None,
    interval_months: int | None,
    today: date,
    validated_on: date | None = None,
) -> date:
    """The next due date (from the interval when given), or RecordError with the screens' code (PRD §9.5). The
    certificate's validation date is optional (pending), but not before the calibration or in the future."""
    if when > today:
        raise RecordError("date_in_future")
    if not (performed_by or "").strip():
        raise RecordError("performed_by_required")
    if interval_months is not None:
        if not 1 <= interval_months <= 120:
            raise RecordError("invalid_interval")
        next_due = add_months(when, interval_months)
    if next_due is None:
        raise RecordError("next_due_required")
    if next_due <= when:
        raise RecordError("next_due_before_date")
    if validated_on is not None:
        if validated_on > today:
            raise RecordError("date_in_future")
        if validated_on < when:
            raise RecordError("validated_before_date")
    return next_due


def check_installed(installed_on: date | None, today: date) -> None:
    if installed_on is not None and installed_on > today:
        raise RecordError("date_in_future")


def check_place(meta: dict[str, Any], today: date) -> None:
    lat, lon = meta.get("lat"), meta.get("lon")
    if lat is not None and not -90 <= lat <= 90:
        raise RecordError("invalid_lat")
    if lon is not None and not -180 <= lon <= 180:
        raise RecordError("invalid_lon")
    year = meta.get("procurement_year")
    if year is not None and not 1950 <= year <= today.year:
        raise RecordError("year_in_future")
    wmo = meta.get("wmo_number")
    if wmo is not None and not (len(wmo) == 5 and wmo.isdigit()):
        raise RecordError("invalid_wmo")


def public_part(part: dict[str, Any], *, full: bool) -> dict[str, Any]:
    """A part as the API shows it: everything for signed-in users; without numbers, notes and authors for the
    public."""
    return part if full else {k: v for k, v in part.items() if k not in PART_SIGNED_IN}


def check_removal(part: dict[str, Any], removed_on: date, today: date) -> None:
    """A part comes out once, not in the future, and not before it went in."""
    if part["removed_on"] is not None:
        raise RecordError("part_already_removed")
    if removed_on > today:
        raise RecordError("date_in_future")
    if part["installed_on"] is not None and removed_on < part["installed_on"]:
        raise RecordError("removed_before_installed")


def check_replacement(removed_on: date, installed_on: date | None) -> None:
    if installed_on is not None and installed_on < removed_on:
        raise RecordError("installed_before_removed")


def same_part_name(a: str, b: str) -> bool:
    return " ".join(a.split()).lower() == " ".join(b.split()).lower()


# ---------------------------------------------------------------------------- database
async def due_soon_days(conn: AsyncConnection) -> int:
    return int(await get_setting(conn, "calibration_due_soon_days", DEFAULT_DUE_SOON_DAYS))


async def summaries(
    conn: AsyncConnection, component_ids: list[int], today: date, window: int, *, as_at: bool = False
) -> dict[int, dict[str, Any]]:
    """Calibration status of each component from its latest record that was not removed.

    ``as_at``: the status as it stood on ``today`` (the monthly report, for a past month): only records dated on
    or before that day count, and a certificate validated later was still pending then.
    """
    rows = await conn.execute(
        text(f"""
        SELECT DISTINCT ON (component_id) component_id, date, next_due,
               CASE WHEN :as_at AND validated_on > :today THEN NULL ELSE validated_on END
        FROM calibration_record
        WHERE removed_at IS NULL AND component_id = ANY(:ids) {"AND date <= :today" if as_at else ""}
        ORDER BY component_id, date DESC, id DESC
    """),
        {"ids": component_ids, "as_at": as_at, "today": today},
    )
    latest = {int(r[0]): (r[1], r[2], r[3]) for r in rows}
    return {
        cid: calibration_status(latest[cid][1], latest[cid][0], today, window, latest[cid][2])
        if cid in latest
        else calibration_status(None, None, today, window)
        for cid in component_ids
    }


async def component_meta(conn: AsyncConnection, component_ids: list[int]) -> dict[int, dict[str, Any]]:
    rows = (
        await conn.execute(
            text(f"SELECT id, {', '.join(COMPONENT_FIELDS)} FROM component WHERE id = ANY(:ids)"),
            {"ids": component_ids},
        )
    ).mappings()
    return {int(r["id"]): {k: r[k] for k in COMPONENT_FIELDS} for r in rows}


async def station_meta(conn: AsyncConnection, system: System) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT name_en, name_id, icao, {', '.join(STATION_FIELDS)} FROM system WHERE id = :id"
                ),
                {"id": system.id},
            )
        )
        .mappings()
        .one()
    )
    return {"name": {"en": row["name_en"], "id": row["name_id"]}, "icao": row["icao"]} | {
        k: row[k] for k in STATION_FIELDS
    }


async def site_meta(conn: AsyncConnection, system: System) -> dict[int, dict[str, Any]]:
    rows = (
        await conn.execute(
            text(f"SELECT id, {', '.join(SITE_FIELDS)} FROM site WHERE system_id = :id"), {"id": system.id}
        )
    ).mappings()
    return {int(r["id"]): {k: r[k] for k in SITE_FIELDS} for r in rows}


async def parts_of(
    conn: AsyncConnection, component_ids: list[int], *, removed: bool = False
) -> dict[int, list[dict[str, Any]]]:
    """Each component's parts: installed ones, or every part ever recorded with ``removed`` (oldest first)."""
    rows = await conn.execute(
        text(f"""
        SELECT {PART_COLUMNS} FROM component_part p LEFT JOIN component_part n ON n.replaces = p.id
        WHERE p.component_id = ANY(:ids) {"" if removed else "AND p.removed_on IS NULL"}
        ORDER BY p.component_id, p.id
    """),
        {"ids": component_ids},
    )
    out: dict[int, list[dict[str, Any]]] = {cid: [] for cid in component_ids}
    for r in rows.mappings():
        out[int(r["component_id"])].append(dict(r))
    return out


async def part_row(conn: AsyncConnection, part_id: int, *, lock: bool = False) -> dict[str, Any] | None:
    if lock:
        await conn.execute(text("SELECT id FROM component_part WHERE id = :id FOR UPDATE"), {"id": part_id})
    row = (
        (
            await conn.execute(
                text(f"""
            SELECT {PART_COLUMNS} FROM component_part p LEFT JOIN component_part n ON n.replaces = p.id
            WHERE p.id = :id
        """),
                {"id": part_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def assets(conn: AsyncConnection, system: System, *, full: bool, today: date) -> dict[str, Any]:
    """What the site pages show: the station, sites and sensors with their installed parts and calibration
    status (FR-REG-004/005). Part and serial numbers are for signed-in users."""
    comps = [(s, c) for s in system.sites for c in s.components]
    ids = [c.id for _, c in comps]
    window = await due_soon_days(conn)
    metas = await component_meta(conn, ids)
    parts = await parts_of(conn, ids)
    cal = await summaries(conn, ids, today, window)
    sites = await site_meta(conn, system)
    return {
        "station": await station_meta(conn, system),
        "sites": [{"slug": s.slug, "meta": sites.get(s.id, {})} for s in system.sites],
        "components": [
            {
                "site": s.slug,
                "type": c.type_code,
                "meta": metas.get(c.id, {}),
                "calibration": cal[c.id],
                "parts": [public_part(p, full=full) for p in parts[c.id]],
            }
            for s, c in comps
        ],
        "due_soon_days": window,
    }


async def calibration_on(conn: AsyncConnection, system: System, day: date) -> dict[str, Any]:
    """Every sensor's calibration status on ``day`` (UTC), for the monthly report (FR-EXP-001 item 8)."""
    comps = [(s, c) for s in system.sites for c in s.components]
    window = await due_soon_days(conn)
    cal = await summaries(conn, [c.id for _, c in comps], day, window, as_at=True)
    return {
        "as_of": day,
        "due_soon_days": window,
        "components": [{"site": s.slug, "type": c.type_code, "calibration": cal[c.id]} for s, c in comps],
    }


async def overdue_problems(conn: AsyncConnection, system: System, today: date) -> list[dict[str, Any]]:
    """Problems panel: one minor item per sensor whose calibration is overdue (FR-DSH-010)."""
    comps = [(s, c) for s in system.sites for c in s.components if not c.is_dcp]
    cal = await summaries(conn, [c.id for _, c in comps], today, await due_soon_days(conn))
    return [
        {
            "code": "calibration_overdue",
            "severity": "minor",
            "link": f"/systems/{system.code}/sites/{s.slug}",
            "params": {"site": s.code, "component": c.type_code, "due": cal[c.id]["next_due"].isoformat()},
        }
        for s, c in comps
        if cal[c.id]["status"] == "overdue"
    ]


# ---------------------------------------------------------------------------- writes (API and import)
def where(system: System, comp: Component) -> str:
    """How the audit log names a component: "<site slug>:<type>"."""
    site = next(s for s in system.sites if s.id == comp.site_id)
    return f"{site.slug}:{comp.type_code}"


def _calibration_view(r: Any) -> dict[str, Any]:
    """A calibration as the API shows it, with the part it covered (R3.7)."""
    row = dict(r)
    role, serial = row.pop("part_role"), row.pop("part_serial")
    row["part"] = (
        {"id": row["part_id"], "role": role, "serial_number": serial} if row["part_id"] is not None else None
    )
    return row


async def calibration_row(conn: AsyncConnection, cal_id: int, *, lock: bool = False) -> dict[str, Any] | None:
    if lock:
        await conn.execute(
            text("SELECT id FROM calibration_record WHERE id = :id AND removed_at IS NULL FOR UPDATE"),
            {"id": cal_id},
        )
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {CALIBRATION_COLUMNS} FROM {CALIBRATION_FROM} WHERE cr.id = :id AND cr.removed_at IS NULL"
                ),
                {"id": cal_id},
            )
        )
        .mappings()
        .first()
    )
    return _calibration_view(row) if row else None


async def calibration_history(conn: AsyncConnection, component_id: int) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text(f"""
        SELECT {CALIBRATION_COLUMNS} FROM {CALIBRATION_FROM} WHERE cr.component_id = :c AND cr.removed_at IS NULL
        ORDER BY cr.date DESC, cr.id DESC
    """),
        {"c": component_id},
    )
    return [_calibration_view(r) for r in rows.mappings()]


async def check_calibration_part(
    conn: AsyncConnection, comp: Component, part_id: int | None, *, installed: bool
) -> None:
    """The part a calibration names must be one of the sensor's parts; a new calibration names an installed one."""
    if part_id is None:
        return
    row = (
        await conn.execute(
            text("SELECT component_id, removed_on FROM component_part WHERE id = :id"), {"id": part_id}
        )
    ).first()
    if row is None or row[0] != comp.id or (installed and row[1] is not None):
        raise RecordError("part_not_installed")


def audit_view(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in CALIBRATION_AUDIT}


async def save_component_meta(
    conn: AsyncConnection,
    system: System,
    comp: Component,
    meta: dict[str, Any],
    *,
    actor: str,
    source_ip: str | None = None,
) -> dict[str, Any]:
    """Replaces a sensor's record with ``meta`` (every field of COMPONENT_FIELDS); audited when anything changed."""
    old = (await component_meta(conn, [comp.id]))[comp.id]
    await conn.execute(
        text(f"UPDATE component SET {', '.join(f'{k} = :{k}' for k in COMPONENT_FIELDS)} WHERE id = :id"),
        {**{k: meta[k] for k in COMPONENT_FIELDS}, "id": comp.id},
    )
    before, after = audit.diff(old, meta)
    if after:
        await audit.record(
            conn,
            "component_meta_changed",
            actor=actor,
            entity_type="component",
            entity_id=where(system, comp),
            before=before,
            after=after,
            source_ip=source_ip,
        )
    return (await component_meta(conn, [comp.id]))[comp.id]


async def add_calibration(
    conn: AsyncConnection,
    system: System,
    comp: Component,
    d: dict[str, Any],
    *,
    actor: str,
    source_ip: str | None = None,
) -> dict[str, Any]:
    """Records a calibration already checked with ``check_calibration`` (``next_due`` filled in); audited."""
    cal_id = (
        await conn.execute(
            text("""
        INSERT INTO calibration_record (component_id, date, performed_by, certificate, next_due, interval_months,
                                        validated_on, notes, part_id, created_by)
        VALUES (:c, :date, :performed_by, :certificate, :next_due, :interval_months, :validated_on, :notes,
                :part_id, :by)
        RETURNING id
    """),
            {**{k: d.get(k) for k in CALIBRATION_AUDIT}, "c": comp.id, "by": actor},
        )
    ).scalar_one()
    row = await calibration_row(conn, cal_id)
    assert row is not None
    await audit.record(
        conn,
        "calibration_added",
        actor=actor,
        entity_type="calibration",
        entity_id=str(cal_id),
        after={"component": where(system, comp), **audit_view(row)},
        source_ip=source_ip,
    )
    return row


# ---------------------------------------------------------------------------- parts (R3.7)
def part_audit_view(p: dict[str, Any]) -> dict[str, Any]:
    """How the audit log shows a part: its name and every recorded field (the log is for Admins)."""
    return {
        "part": p["role"],
        "part_id": p["id"],
        **{k: p[k] for k in PART_FIELDS if k != "role"},
        "removed_on": p["removed_on"],
        "removed_reason": p["removed_reason"],
    }


async def add_part(
    conn: AsyncConnection,
    system: System,
    comp: Component,
    d: dict[str, Any],
    *,
    actor: str,
    source_ip: str | None = None,
    replaces: int | None = None,
) -> dict[str, Any]:
    """Adds an installed part (fields checked by the caller). Audited as ``part_added`` unless it replaces one, which
    ``replace_part`` audits as a whole."""
    part_id = (
        await conn.execute(
            text("""
        INSERT INTO component_part (component_id, role, manufacturer, model, part_number, serial_number, firmware,
                                    installed_on, notes, replaces, created_by)
        VALUES (:c, :role, :manufacturer, :model, :part_number, :serial_number, :firmware, :installed_on, :notes,
                :replaces, :by)
        RETURNING id
    """),
            {**{k: d.get(k) for k in PART_FIELDS}, "c": comp.id, "replaces": replaces, "by": actor},
        )
    ).scalar_one()
    row = await part_row(conn, part_id)
    assert row is not None
    if replaces is None:
        await audit.record(
            conn,
            "part_added",
            actor=actor,
            entity_type="component",
            entity_id=where(system, comp),
            after=part_audit_view(row),
            source_ip=source_ip,
        )
    return row


async def update_part(
    conn: AsyncConnection,
    system: System,
    comp: Component,
    old: dict[str, Any],
    d: dict[str, Any],
    *,
    actor: str,
    source_ip: str | None = None,
) -> dict[str, Any]:
    """Corrects a part's record (a typing mistake, a missing number): not a replacement. Audited with before and
    after."""
    if old["removed_on"] is not None and d.get("installed_on") and d["installed_on"] > old["removed_on"]:
        raise RecordError("removed_before_installed")
    await conn.execute(
        text(f"""
        UPDATE component_part SET {", ".join(f"{k} = :{k}" for k in PART_FIELDS)}, updated_by = :by,
               updated_at = now()
        WHERE id = :id
    """),
        {**{k: d.get(k) for k in PART_FIELDS}, "by": actor, "id": old["id"]},
    )
    row = await part_row(conn, old["id"])
    assert row is not None
    before, after = audit.diff(part_audit_view(old), part_audit_view(row))
    if after:
        await audit.record(
            conn,
            "part_changed",
            actor=actor,
            entity_type="component",
            entity_id=where(system, comp),
            before={"part": old["role"], "part_id": old["id"], **before},
            after=after,
            source_ip=source_ip,
        )
    return row


async def _close_part(
    conn: AsyncConnection, part_id: int, removed_on: date, reason: str | None, actor: str
) -> dict[str, Any]:
    await conn.execute(
        text("""
        UPDATE component_part SET removed_on = :on, removed_reason = :reason, updated_by = :by, updated_at = now()
        WHERE id = :id
    """),
        {"on": removed_on, "reason": reason, "by": actor, "id": part_id},
    )
    row = await part_row(conn, part_id)
    assert row is not None
    return row


async def remove_part(
    conn: AsyncConnection,
    system: System,
    comp: Component,
    old: dict[str, Any],
    removed_on: date,
    reason: str | None,
    *,
    actor: str,
    source_ip: str | None = None,
) -> dict[str, Any]:
    """Takes a part out without a replacement. The row stays as history; audited as ``part_removed``."""
    row = await _close_part(conn, old["id"], removed_on, reason, actor)
    await audit.record(
        conn,
        "part_removed",
        actor=actor,
        entity_type="component",
        entity_id=where(system, comp),
        before=part_audit_view(old),
        after={"part": row["role"], "part_id": row["id"], "removed_on": removed_on, "removed_reason": reason},
        source_ip=source_ip,
    )
    return row


async def replace_part(
    conn: AsyncConnection,
    system: System,
    comp: Component,
    old: dict[str, Any],
    removed_on: date,
    reason: str | None,
    d: dict[str, Any],
    *,
    actor: str,
    source_ip: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A physical swap: the old part is removed on ``removed_on`` and the new one installed in its place, linked
    to it. One audit entry, ``part_replaced``, holds both."""
    removed = await _close_part(conn, old["id"], removed_on, reason, actor)
    added = await add_part(conn, system, comp, d, actor=actor, replaces=old["id"])
    removed = await part_row(conn, old["id"]) or removed  # now with replaced_by
    await audit.record(
        conn,
        "part_replaced",
        actor=actor,
        entity_type="component",
        entity_id=where(system, comp),
        before=part_audit_view(removed),
        after=part_audit_view(added),
        source_ip=source_ip,
    )
    return removed, added


def _json(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


async def trace(
    conn: AsyncConnection, system: System, slug: str, comp: Component, a: datetime, b: datetime
) -> list[dict[str, Any]]:
    """FR-AUD-003: the changes that moved one component's figures in [a, b): flags on it, decisions on its
    mandatory-field detections, mandatory-field changes of its type (every period), changes of its in-service
    period, and reprocess or recompute jobs over the period. Newest first."""
    params: dict[str, Any] = {"c": comp.id, "a": a, "b": b}
    flags = {
        str(r[0]): {"flag": r[0], "reason": r[1], "start": r[2], "end": r[3]}
        for r in await conn.execute(
            text("""
            SELECT DISTINCT f.id, f.reason, f.start_at, f.end_at FROM flag f JOIN flag_component fc ON fc.flag_id = f.id
            WHERE fc.component_id = :c AND f.end_at > :a AND f.start_at < :b
        """),
            params,
        )
    }
    detections = {
        str(r[0]): {"detection": r[0], "field": r[1], "type": r[2], "start": r[3], "end": r[4]}
        for r in await conn.execute(
            text("""
            SELECT id, field_code, type, start_at, end_at FROM dq_detection
            WHERE component_id = :c AND end_at > :a AND start_at < :b AND field_code = ANY(:mand)
        """),
            {**params, "mand": list(comp.mandatory)},
        )
    }
    rows = (
        await conn.execute(
            text("""
        SELECT id, time, actor, action, entity_type, entity_id, before, after FROM audit_event
        WHERE (entity_type = 'flag' AND entity_id = ANY(:flags)
               AND action IN ('flag_created', 'flag_updated', 'flag_removed'))
           OR (entity_type = 'detection' AND entity_id = ANY(:dets) AND action = 'detections_decided')
           OR (entity_type = 'mandatory' AND entity_id = :type AND action = 'mandatory_changed')
           OR (entity_type = 'component' AND entity_id = :key AND action = 'in_service_changed')
        ORDER BY time DESC, id DESC LIMIT 200
    """),
            {
                "flags": list(flags),
                "dets": list(detections),
                "type": comp.type_code,
                "key": f"{slug}:{comp.type_code}",
            },
        )
    ).mappings()
    out: list[dict[str, Any]] = []
    for r in rows:
        before, after = _json(r["before"]) or {}, _json(r["after"]) or {}
        if r["entity_type"] == "flag":
            detail: dict[str, Any] = flags[r["entity_id"]]
        elif r["entity_type"] == "detection":
            detail = {**detections[r["entity_id"]], "status": after.get("status")}
        elif r["entity_type"] == "mandatory":
            detail = {"before": before.get("fields"), "after": after.get("fields")}
        else:
            detail = {k: after.get(k) for k in ("in_service_from", "in_service_to")}
        out.append(
            {
                "id": r["id"],
                "time": r["time"],
                "actor": r["actor"],
                "action": r["action"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "detail": detail,
            }
        )
    for job_id, job_type, jp, by, at in await conn.execute(
        text("""
        SELECT id, type, params, created_by, created_at FROM job
        WHERE type IN ('reprocess', 'recompute') AND status <> 'cancelled' AND params->>'system' = :code
          AND params->>'from' <= :last AND params->>'to' >= :first
        ORDER BY created_at DESC LIMIT 50
    """),
        {
            "code": system.code,
            "first": a.date().isoformat(),
            "last": (b - timedelta(minutes=1)).date().isoformat(),
        },
    ):
        jp = _json(jp)
        out.append(
            {
                "id": -int(job_id),
                "time": at,
                "actor": by,
                "action": "job_started",
                "entity_type": "job",
                "entity_id": str(job_id),
                "detail": {"job": job_id, "type": job_type, "from": jp.get("from"), "to": jp.get("to")},
            }
        )
    return sorted(out, key=lambda e: e["time"], reverse=True)
