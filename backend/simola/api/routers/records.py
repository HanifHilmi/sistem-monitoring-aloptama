"""Station, site and sensor records, sensor parts and calibration (R2.5, R3.7, FR-REG-004/005, FR-AUD-003).

- Everyone sees the records, each sensor's installed parts and its calibration status; part and serial numbers,
  part notes and who changed them are for signed-in users.
- Admins add, correct, replace and remove parts. A replacement closes the old part and adds the new one, so the
  history of what was installed when is kept.
- The figure change trace (which changes moved a component's figures in a period) is for signed-in users.
- Admins edit the records and record, correct or remove calibrations. Every change is audited in its transaction.
  Nothing here changes a figure, so nothing is recomputed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable
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
    """The sensor as a whole; models and numbers belong to its parts (R3.7)."""

    sensor_type: str | None = Field(max_length=100)
    installed_on: dt.date | None
    notes: str | None = Field(max_length=500)


class PartBody(_Body):
    role: str | None = Field(None, max_length=60)  # required: checked with the screens' code
    manufacturer: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    part_number: str | None = Field(None, max_length=100)
    serial_number: str | None = Field(None, max_length=100)
    firmware: str | None = Field(None, max_length=100)
    installed_on: dt.date | None = None
    notes: str | None = Field(None, max_length=500)


class RemoveBody(_Body):
    removed_on: dt.date
    notes: str | None = Field(None, max_length=500)  # the reason, kept with the removed part


class ReplaceBody(RemoveBody):
    part: PartBody


class CalibrationBody(_Body):
    component_id: int
    date: dt.date
    performed_by: str | None = Field(None, max_length=100)  # required: checked with the screens' code
    certificate: str | None = Field(None, max_length=100)
    next_due: dt.date | None = None
    interval_months: int | None = None
    validated_on: dt.date | None = None  # empty while the certificate is pending
    notes: str | None = Field(None, max_length=500)
    part_id: int | None = None  # R3.7: the part the certificate names; null for the sensor as a whole


def _check(fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except records.RecordError as exc:
        raise ApiError(422, exc.code, exc.code.replace("_", " ")) from exc


async def _acheck[T](coro: Awaitable[T]) -> T:
    try:
        return await coro
    except records.RecordError as exc:
        raise ApiError(422, exc.code, exc.code.replace("_", " ")) from exc


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
    _check(records.check_installed, meta["installed_on"], _today())
    async with get_engine().begin() as conn:
        sy, comp = await _component(conn, component_id, lock=True)
        return await records.save_component_meta(
            conn, sy, comp, meta, actor=admin.username, source_ip=client_ip(request)
        )


# ------------------------------------------------------------------------------------------ calibration
async def _calibration(conn: AsyncConnection, cal_id: int, *, lock: bool = False) -> dict[str, Any]:
    row = await records.calibration_row(conn, cal_id, lock=lock)
    if row is None:
        raise ApiError(404, "calibration_not_found", "no such calibration")
    return row


def _validated(body: CalibrationBody) -> dict[str, Any]:
    d = body.model_dump()
    d["next_due"] = _check(
        records.check_calibration,
        d["date"],
        d["performed_by"],
        d["next_due"],
        d["interval_months"],
        _today(),
        d["validated_on"],
    )
    return d


@admin_router.get("/components/{component_id}/calibrations")
async def list_calibrations(component_id: int) -> list[dict[str, Any]]:
    """A sensor's calibrations, newest first. Removed ones stay in the database and the audit log."""
    async with get_engine().connect() as conn:
        await _component(conn, component_id)
        return await records.calibration_history(conn, component_id)


@admin_router.post("/calibrations", status_code=201)
async def add_calibration(
    body: CalibrationBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    async with get_engine().begin() as conn:
        sy, comp = await _component(conn, body.component_id, lock=True)
        if comp.is_dcp:
            raise ApiError(422, "dcp_not_calibrated", "a DCP is not calibrated")
        await _acheck(records.check_calibration_part(conn, comp, body.part_id, installed=True))
        return await records.add_calibration(
            conn, sy, comp, _validated(body), actor=admin.username, source_ip=client_ip(request)
        )


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
        await _acheck(records.check_calibration_part(conn, comp, body.part_id, installed=False))
        await conn.execute(
            text("""
            UPDATE calibration_record SET date = :date, performed_by = :performed_by, certificate = :certificate,
                   next_due = :next_due, interval_months = :interval_months, validated_on = :validated_on,
                   notes = :notes, part_id = :part_id, updated_by = :by, updated_at = now()
            WHERE id = :id
        """),
            {**{k: d[k] for k in records.CALIBRATION_AUDIT}, "by": admin.username, "id": cal_id},
        )
        row = await _calibration(conn, cal_id)
        before, after = audit.diff(records.audit_view(old), records.audit_view(row))
        if after:
            await audit.record(
                conn,
                "calibration_changed",
                actor=admin.username,
                entity_type="calibration",
                entity_id=str(cal_id),
                before={"component": records.where(sy, comp), **before},
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
            before={"component": records.where(sy, comp), **records.audit_view(old)},
            source_ip=client_ip(request),
        )
    return {"removed": cal_id}


# ------------------------------------------------------------------------------------------ parts (R3.7)
def _part_fields(body: PartBody) -> dict[str, Any]:
    d = body.model_dump()
    if not d["role"]:
        raise ApiError(422, "role_required", "name the part")
    d["role"] = " ".join(d["role"].split())
    _check(records.check_installed, d["installed_on"], _today())
    return d


async def _part(conn: AsyncConnection, part_id: int, *, lock: bool = False) -> dict[str, Any]:
    row = await records.part_row(conn, part_id, lock=lock)
    if row is None:
        raise ApiError(404, "part_not_found", "no such part")
    return row


@admin_router.get("/components/{component_id}/parts")
async def list_parts(component_id: int, removed: bool = False) -> list[dict[str, Any]]:
    """A sensor's installed parts; with ``removed=1`` every part ever recorded, removed ones included."""
    async with get_engine().connect() as conn:
        await _component(conn, component_id)
        return (await records.parts_of(conn, [component_id], removed=removed))[component_id]


@admin_router.post("/components/{component_id}/parts", status_code=201)
async def add_part(
    component_id: int, body: PartBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    d = _part_fields(body)
    async with get_engine().begin() as conn:
        sy, comp = await _component(conn, component_id, lock=True)
        return await records.add_part(conn, sy, comp, d, actor=admin.username, source_ip=client_ip(request))


@admin_router.patch("/parts/{part_id}")
async def update_part(
    part_id: int, body: PartBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Corrects a part's record. A physical swap is a replacement, not a correction."""
    d = _part_fields(body)
    async with get_engine().begin() as conn:
        old = await _part(conn, part_id, lock=True)
        sy, comp = await _component(conn, old["component_id"])
        return await _acheck(
            records.update_part(conn, sy, comp, old, d, actor=admin.username, source_ip=client_ip(request))
        )


@admin_router.post("/parts/{part_id}/remove")
async def remove_part(
    part_id: int, body: RemoveBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Takes a part out without a replacement; it stays in the history."""
    async with get_engine().begin() as conn:
        old = await _part(conn, part_id, lock=True)
        _check(records.check_removal, old, body.removed_on, _today())
        sy, comp = await _component(conn, old["component_id"])
        return await records.remove_part(
            conn,
            sy,
            comp,
            old,
            body.removed_on,
            body.notes,
            actor=admin.username,
            source_ip=client_ip(request),
        )


@admin_router.post("/parts/{part_id}/replace")
async def replace_part(
    part_id: int, body: ReplaceBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """A physical swap: the old part is removed on ``removed_on`` and the new one installed in its place."""
    d = _part_fields(body.part)
    async with get_engine().begin() as conn:
        old = await _part(conn, part_id, lock=True)
        _check(records.check_removal, old, body.removed_on, _today())
        _check(records.check_replacement, body.removed_on, d["installed_on"])
        sy, comp = await _component(conn, old["component_id"])
        removed, added = await records.replace_part(
            conn,
            sy,
            comp,
            old,
            body.removed_on,
            body.notes,
            d,
            actor=admin.username,
            source_ip=client_ip(request),
        )
        return {"removed": removed, "added": added}
