"""Station, site and sensor records, calibration status and the figure change trace (R2.5).

PRD FR-REG-004 (records; serial and part numbers hidden from the public), FR-REG-005 (calibration history and a
status derived on read: OK, due soon, overdue, unknown), FR-AUD-003 (which changes moved a component's figures).
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.registry import Component, System, get_setting

STATION_FIELDS = ("wmo_number", "airport_name", "lat", "lon", "elevation_m", "procurement_year", "notes")
SITE_FIELDS = ("lat", "lon", "elevation_m", "threshold_elevation_m", "description")
COMPONENT_FIELDS = (
    "sensor_type",
    "manufacturer",
    "model",
    "part_number",
    "serial_number",
    "installed_on",
    "firmware",
    "notes",
)
PRIVATE_FIELDS = ("part_number", "serial_number")  # signed-in users only (PRD §5.4, OPEN-13)
DEFAULT_DUE_SOON_DAYS = 30


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


def calibration_status(next_due: date | None, last: date | None, today: date, window: int) -> dict[str, Any]:
    """FR-REG-005: overdue once the due date has passed, due soon within ``window`` days, otherwise OK; unknown
    without a record. Dates are UTC."""
    if next_due is None:
        return {"status": "unknown", "last": None, "next_due": None, "days_left": None}
    left = (next_due - today).days
    status = "overdue" if left < 0 else "due_soon" if left <= window else "ok"
    return {"status": status, "last": last, "next_due": next_due, "days_left": left}


def check_calibration(
    when: date, performed_by: str | None, next_due: date | None, interval_months: int | None, today: date
) -> date:
    """The next due date (from the interval when given), or RecordError with the screens' code (PRD §9.5)."""
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
    return next_due


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


def public_meta(meta: dict[str, Any], *, full: bool) -> dict[str, Any]:
    return meta if full else {k: v for k, v in meta.items() if k not in PRIVATE_FIELDS}


# ---------------------------------------------------------------------------- database
async def due_soon_days(conn: AsyncConnection) -> int:
    return int(await get_setting(conn, "calibration_due_soon_days", DEFAULT_DUE_SOON_DAYS))


async def summaries(
    conn: AsyncConnection, component_ids: list[int], today: date, window: int
) -> dict[int, dict[str, Any]]:
    """Calibration status of each component from its latest record that was not removed."""
    rows = await conn.execute(
        text("""
        SELECT DISTINCT ON (component_id) component_id, date, next_due FROM calibration_record
        WHERE removed_at IS NULL AND component_id = ANY(:ids)
        ORDER BY component_id, date DESC, id DESC
    """),
        {"ids": component_ids},
    )
    latest = {int(r[0]): (r[1], r[2]) for r in rows}
    return {
        cid: calibration_status(latest[cid][1], latest[cid][0], today, window)
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


async def assets(conn: AsyncConnection, system: System, *, full: bool, today: date) -> dict[str, Any]:
    """What the site pages show: the station, sites and sensors, with calibration status (FR-REG-004/005)."""
    comps = [(s, c) for s in system.sites for c in s.components]
    ids = [c.id for _, c in comps]
    window = await due_soon_days(conn)
    metas = await component_meta(conn, ids)
    cal = await summaries(conn, ids, today, window)
    sites = await site_meta(conn, system)
    return {
        "station": await station_meta(conn, system),
        "sites": [{"slug": s.slug, "meta": sites.get(s.id, {})} for s in system.sites],
        "components": [
            {
                "site": s.slug,
                "type": c.type_code,
                "meta": public_meta(metas.get(c.id, {}), full=full),
                "calibration": cal[c.id],
            }
            for s, c in comps
        ],
        "due_soon_days": window,
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
