"""Station, site and sensor records and calibration (R2.5, FR-REG-004/005, FR-AUD-003).

- Everyone sees the records and each sensor's calibration status; serial and part numbers are for signed-in users.
- The figure change trace (which changes moved a component's figures in a period) is for signed-in users.
- Admins edit the records and record, correct or remove calibrations. Every change is audited in its transaction.
  Nothing here changes a figure, so nothing is recomputed.
"""

from __future__ import annotations

import datetime as dt
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import records
from simola.api.deps import ApiError, parse_period, system_or_404
from simola.api.routers.admin_ops import DEFAULT_SYSTEM, _system, _today
from simola.api.security import client_ip, csrf, principal, require_admin, require_viewer
from simola.auth import audit
from simola.auth.sessions import Principal
from simola.core.db import connection, get_engine
from simola.registry import Component, System

router = APIRouter(prefix="/api/v1", tags=["records"])
admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin), Depends(csrf)]
)

MAX_TRACE_SPAN = timedelta(days=366)
CALIBRATION_COLUMNS = (
    "id, component_id, date, performed_by, certificate, next_due, interval_months, notes, "
    "created_by, created_at, updated_by, updated_at"
)


def _blank(v: Any) -> Any:
    """Text fields: surrounding spaces dropped, and empty means not given."""
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class _Body(BaseModel):
    """A PUT replaces the whole record, so every field must be sent (null to clear it)."""

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return _blank(v)


class StationBody(_Body):
    wmo_number: str | None
    airport_name: str | None = Field(max_length=120)
    lat: float | None
    lon: float | None
    elevation_m: float | None = Field(ge=-500, le=9000)
    procurement_year: int | None
    notes: str | None = Field(max_length=500)


class SiteBody(_Body):
    lat: float | None
    lon: float | None
    elevation_m: float | None = Field(ge=-500, le=9000)
    threshold_elevation_m: float | None = Field(ge=-500, le=9000)
    description: str | None = Field(max_length=500)


class ComponentMetaBody(_Body):
    sensor_type: str | None = Field(max_length=100)
    manufacturer: str | None = Field(max_length=100)
    model: str | None = Field(max_length=100)
    part_number: str | None = Field(max_length=100)
    serial_number: str | None = Field(max_length=100)
    installed_on: dt.date | None
    firmware: str | None = Field(max_length=100)
    notes: str | None = Field(max_length=500)


class CalibrationBody(_Body):
    component_id: int
    date: dt.date
    performed_by: str | None = Field(None, max_length=100)  # required: checked with the screens' code
    certificate: str | None = Field(None, max_length=100)
    next_due: dt.date | None = None
    interval_months: int | None = None
    notes: str | None = Field(None, max_length=500)


def _check(fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except records.RecordError as exc:
        raise ApiError(422, exc.code, exc.code.replace("_", " ")) from exc


def _where(system: System, comp: Component) -> str:
    site = next(s for s in system.sites if s.id == comp.site_id)
    return f"{site.slug}:{comp.type_code}"


# ------------------------------------------------------------------------------------------ public
@router.get("/systems/{code}/assets")
async def get_assets(
    request: Request, code: str, conn: AsyncConnection = Depends(connection)
) -> dict[str, Any]:
    """The station, its sites and sensors with calibration status (FR-REG-004/005). Serial and part numbers are
    for signed-in users (PRD §5.4)."""
    system = await system_or_404(conn, code)
    user = await principal(request)
    full = user is not None and not user.must_change_password
    return await records.assets(conn, system, full=full, today=_today())


@router.get("/systems/{code}/trace")
async def get_trace(
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    scope: str = Query(pattern=r"^component:[a-z0-9-]+:[A-Z0-9]+$"),
    viewer: Principal = Depends(require_viewer),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """The changes that moved one component's figures in a period, newest first (FR-AUD-003)."""
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_TRACE_SPAN)
    _, slug, type_code = scope.split(":")
    site = system.site_by_slug(slug)
    comp = next((c for c in site.components if c.type_code == type_code), None) if site else None
    if comp is None:
        raise ApiError(404, "scope_not_found", f"unknown scope {scope!r}")
    return await records.trace(conn, system, slug, comp, start, end)


# ------------------------------------------------------------------------------------------ station and sites
@admin_router.get("/station")
async def get_station(system: str = DEFAULT_SYSTEM) -> dict[str, Any]:
    async with get_engine().connect() as conn:
        return await records.station_meta(conn, await _system(conn, system))


@admin_router.put("/station")
async def put_station(
    body: StationBody,
    request: Request,
    system: str = DEFAULT_SYSTEM,
    admin: Principal = Depends(require_admin),
) -> dict[str, Any]:
    meta = body.model_dump()
    _check(records.check_place, meta, _today())
    async with get_engine().begin() as conn:
        sy = await _system(conn, system)
        await conn.execute(text("SELECT id FROM system WHERE id = :id FOR UPDATE"), {"id": sy.id})
        old = await records.station_meta(conn, sy)
        await conn.execute(
            text(
                f"UPDATE system SET {', '.join(f'{k} = :{k}' for k in records.STATION_FIELDS)} WHERE id = :id"
            ),
            {**meta, "id": sy.id},
        )
        before, after = audit.diff({k: old[k] for k in records.STATION_FIELDS}, meta)
        if after:
            await audit.record(
                conn,
                "station_changed",
                actor=admin.username,
                entity_type="system",
                entity_id=sy.code,
                before=before,
                after=after,
                source_ip=client_ip(request),
            )
        return await records.station_meta(conn, sy)


@admin_router.put("/sites/{slug}")
async def put_site(
    slug: str,
    body: SiteBody,
    request: Request,
    system: str = DEFAULT_SYSTEM,
    admin: Principal = Depends(require_admin),
) -> dict[str, Any]:
    meta = body.model_dump()
    _check(records.check_place, meta, _today())
    async with get_engine().begin() as conn:
        sy = await _system(conn, system)
        site = sy.site_by_slug(slug)
        if site is None:
            raise ApiError(404, "site_not_found", f"unknown site {slug!r}")
        await conn.execute(text("SELECT id FROM site WHERE id = :id FOR UPDATE"), {"id": site.id})
        old = (await records.site_meta(conn, sy))[site.id]
        await conn.execute(
            text(f"UPDATE site SET {', '.join(f'{k} = :{k}' for k in records.SITE_FIELDS)} WHERE id = :id"),
            {**meta, "id": site.id},
        )
        before, after = audit.diff(old, meta)
        if after:
            await audit.record(
                conn,
                "site_changed",
                actor=admin.username,
                entity_type="site",
                entity_id=site.slug,
                before=before,
                after=after,
                source_ip=client_ip(request),
            )
        return (await records.site_meta(conn, sy))[site.id]


# ------------------------------------------------------------------------------------------ sensors
async def _component(
    conn: AsyncConnection, component_id: int, *, lock: bool = False
) -> tuple[System, Component]:
    row = (
        await conn.execute(
            text(f"""
            SELECT sy.code FROM component c JOIN site st ON st.id = c.site_id JOIN system sy ON sy.id = st.system_id
            WHERE c.id = :id {"FOR UPDATE OF c" if lock else ""}
        """),
            {"id": component_id},
        )
    ).first()
    if row is None:
        raise ApiError(404, "component_not_found", "no such component")
    sy = await _system(conn, row[0])
    return sy, next(c for s in sy.sites for c in s.components if c.id == component_id)


@admin_router.put("/components/{component_id}/meta")
async def put_component_meta(
    component_id: int, body: ComponentMetaBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    meta = body.model_dump()
    if meta["installed_on"] and meta["installed_on"] > _today():
        raise ApiError(422, "date_in_future", "installed on cannot be in the future")
    async with get_engine().begin() as conn:
        sy, comp = await _component(conn, component_id, lock=True)
        old = (await records.component_meta(conn, [comp.id]))[comp.id]
        await conn.execute(
            text(
                f"UPDATE component SET {', '.join(f'{k} = :{k}' for k in records.COMPONENT_FIELDS)} WHERE id = :id"
            ),
            {**meta, "id": comp.id},
        )
        before, after = audit.diff(old, meta)
        if after:
            await audit.record(
                conn,
                "component_meta_changed",
                actor=admin.username,
                entity_type="component",
                entity_id=_where(sy, comp),
                before=before,
                after=after,
                source_ip=client_ip(request),
            )
        return (await records.component_meta(conn, [comp.id]))[comp.id]


# ------------------------------------------------------------------------------------------ calibration
async def _calibration(conn: AsyncConnection, cal_id: int, *, lock: bool = False) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(f"""
            SELECT {CALIBRATION_COLUMNS} FROM calibration_record WHERE id = :id AND removed_at IS NULL
            {"FOR UPDATE" if lock else ""}
        """),
                {"id": cal_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, "calibration_not_found", "no such calibration")
    return dict(row)


def _audit_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("date", "performed_by", "certificate", "next_due", "interval_months", "notes")
    return {k: row[k] for k in keys}


def _validated(body: CalibrationBody) -> dict[str, Any]:
    d = body.model_dump()
    d["next_due"] = _check(
        records.check_calibration, d["date"], d["performed_by"], d["next_due"], d["interval_months"], _today()
    )
    return d


@admin_router.get("/components/{component_id}/calibrations")
async def list_calibrations(component_id: int) -> list[dict[str, Any]]:
    """A sensor's calibrations, newest first. Removed ones stay in the database and the audit log."""
    async with get_engine().connect() as conn:
        await _component(conn, component_id)
        rows = await conn.execute(
            text(f"""
            SELECT {CALIBRATION_COLUMNS} FROM calibration_record WHERE component_id = :c AND removed_at IS NULL
            ORDER BY date DESC, id DESC
        """),
            {"c": component_id},
        )
        return [dict(r) for r in rows.mappings()]


@admin_router.post("/calibrations", status_code=201)
async def add_calibration(
    body: CalibrationBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    async with get_engine().begin() as conn:
        sy, comp = await _component(conn, body.component_id, lock=True)
        if comp.is_dcp:
            raise ApiError(422, "dcp_not_calibrated", "a DCP is not calibrated")
        d = _validated(body)
        cal_id = (
            await conn.execute(
                text("""
            INSERT INTO calibration_record (component_id, date, performed_by, certificate, next_due, interval_months,
                                            notes, created_by)
            VALUES (:component_id, :date, :performed_by, :certificate, :next_due, :interval_months, :notes, :by)
            RETURNING id
        """),
                {**d, "by": admin.username},
            )
        ).scalar_one()
        row = await _calibration(conn, cal_id)
        await audit.record(
            conn,
            "calibration_added",
            actor=admin.username,
            entity_type="calibration",
            entity_id=str(cal_id),
            after={"component": _where(sy, comp), **_audit_view(row)},
            source_ip=client_ip(request),
        )
        return row


@admin_router.patch("/calibrations/{cal_id}")
async def update_calibration(
    cal_id: int, body: CalibrationBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Corrects a calibration: the whole record is replaced. It stays on its sensor."""
    async with get_engine().begin() as conn:
        old = await _calibration(conn, cal_id, lock=True)
        if body.component_id != old["component_id"]:
            raise ApiError(422, "component_mismatch", "a calibration stays on its sensor")
        sy, comp = await _component(conn, old["component_id"])
        d = _validated(body)
        await conn.execute(
            text("""
            UPDATE calibration_record SET date = :date, performed_by = :performed_by, certificate = :certificate,
                   next_due = :next_due, interval_months = :interval_months, notes = :notes,
                   updated_by = :by, updated_at = now()
            WHERE id = :id
        """),
            {**d, "by": admin.username, "id": cal_id},
        )
        row = await _calibration(conn, cal_id)
        before, after = audit.diff(_audit_view(old), _audit_view(row))
        if after:
            await audit.record(
                conn,
                "calibration_changed",
                actor=admin.username,
                entity_type="calibration",
                entity_id=str(cal_id),
                before={"component": _where(sy, comp), **before},
                after=after,
                source_ip=client_ip(request),
            )
        return row


@admin_router.delete("/calibrations/{cal_id}")
async def remove_calibration(
    cal_id: int, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, int]:
    """Removes a calibration from the history. The row is kept (PRD §9.6) and the status falls back to the
    previous record."""
    async with get_engine().begin() as conn:
        old = await _calibration(conn, cal_id, lock=True)
        sy, comp = await _component(conn, old["component_id"])
        await conn.execute(
            text("UPDATE calibration_record SET removed_by = :by, removed_at = now() WHERE id = :id"),
            {"by": admin.username, "id": cal_id},
        )
        await audit.record(
            conn,
            "calibration_removed",
            actor=admin.username,
            entity_type="calibration",
            entity_id=str(cal_id),
            before={"component": _where(sy, comp), **_audit_view(old)},
            source_ip=client_ip(request),
        )
    return {"removed": cal_id}
