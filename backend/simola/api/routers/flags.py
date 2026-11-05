"""Manual flags (R2.3, FR-DQ-006/007): time ranges an Admin marks as bad data on one or more components.

- Everyone sees a flag's time and reason category; the note and who flagged it are for signed-in users, since a
  note may mention internal details (docs/design/r2.md §4.7).
- Admins create, edit and remove flags. Each change writes the flag, its invalidating intervals (what the engine
  reads) and the audit entry in one transaction, and queues a recompute of the days it touches (FR-KPI-008).
- A flag covers the past only, never a DCP, and only otherwise-valid minutes count as lost: a minute already lost
  for another reason keeps that reason (kpi/outages.py, kpi/minutes.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.api.deps import ApiError, parse_period, system_or_404
from simola.api.routers.admin_ops import DEFAULT_SYSTEM, _enqueue, _system, _today
from simola.api.security import client_ip, csrf, principal, require_admin
from simola.auth import audit
from simola.auth.sessions import Principal
from simola.core.db import connection, get_engine
from simola.core.timeutil import MINUTE, ceil_minute, floor_minute, minutes_between
from simola.kpi import engine
from simola.registry import Component, System

REASONS = ("sensor_fault", "maintenance", "calibration", "environmental", "other")
NOTE_MIN, NOTE_MAX = 3, 500
MAX_LIST_SPAN = timedelta(days=366)
MAX_PREVIEW_SPAN = timedelta(days=366)

router = APIRouter(prefix="/api/v1", tags=["flags"])
admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin), Depends(csrf)]
)

FLAG_SELECT = """
    SELECT f.id, f.start_at, f.end_at, f.reason, f.note, f.created_by, f.created_at, f.updated_by, f.updated_at,
           f.removed_by, f.removed_at, array_agg(fc.component_id ORDER BY fc.component_id) AS component_ids
    FROM flag f JOIN flag_component fc ON fc.flag_id = f.id
"""


# ------------------------------------------------------------------------------------------ rules (pure)
@dataclass(frozen=True)
class Draft:
    components: tuple[Component, ...]
    start: datetime
    end: datetime
    reason: str
    note: str


class FlagBody(BaseModel):
    system: str = DEFAULT_SYSTEM
    component_ids: list[int] = Field(default_factory=list, max_length=100)
    start: datetime
    end: datetime
    reason: str = Field(max_length=40)
    note: str = Field(default="", max_length=2000)


def check_flag(system: System, body: FlagBody, now: datetime) -> Draft:
    """The flag to store, or ApiError 422 with a code the screens translate."""
    by_id = {c.id: c for s in system.sites for c in s.components}
    ids = list(dict.fromkeys(body.component_ids))
    if not ids:
        raise ApiError(422, "no_components", "pick at least one component")
    if any(i not in by_id for i in ids):
        raise ApiError(422, "component_not_found", "a component is not part of this system")
    comps = tuple(sorted((by_id[i] for i in ids), key=lambda c: c.id))
    if any(c.is_dcp for c in comps):
        raise ApiError(422, "dcp_cannot_be_flagged", "a DCP cannot be flagged")
    if body.start.tzinfo is None or body.end.tzinfo is None:
        raise ApiError(422, "invalid_time", "start and end need a UTC offset")
    start, end = floor_minute(body.start), floor_minute(body.end)
    if start >= end:
        raise ApiError(422, "invalid_period", "start must be before end")
    if end > ceil_minute(now):
        raise ApiError(422, "flag_in_future", "flags cover the past only")
    if start < floor_minute(system.coverage_start):
        raise ApiError(422, "before_coverage", "the range starts before SIMOLA has data")
    if body.reason not in REASONS:
        raise ApiError(422, "invalid_reason", f"reason must be one of {', '.join(REASONS)}")
    note = body.note.strip()
    if len(note) < NOTE_MIN:
        raise ApiError(422, "note_required", f"write a note of at least {NOTE_MIN} characters")
    if len(note) > NOTE_MAX:
        raise ApiError(422, "note_too_long", f"the note is longer than {NOTE_MAX} characters")
    return Draft(comps, start, end, body.reason, note)


def flag_days(start: datetime, end: datetime, coverage: date, today: date) -> tuple[date, date] | None:
    """The UTC days whose figures a flag over [start, end) changes, up to today."""
    first, last = max(start.date(), coverage), min((end - MINUTE).date(), today)
    return (first, last) if first <= last else None


def union_days(*spans: tuple[date, date] | None) -> tuple[date, date] | None:
    found = [s for s in spans if s]
    return (min(s[0] for s in found), max(s[1] for s in found)) if found else None


def _component_ref(system: System, comp_id: int) -> dict[str, str]:
    for s in system.sites:
        for c in s.components:
            if c.id == comp_id:
                return {"site": s.slug, "type": c.type_code}
    return {"site": "?", "type": "?"}


def flag_view(system: System, row: Any, *, full: bool) -> dict[str, Any]:
    """A flag for charts and the minute view; note and author only when ``full``."""
    view: dict[str, Any] = {
        "id": row["id"],
        "reason": row["reason"],
        "start": row["start_at"],
        "end": row["end_at"],
        "components": [_component_ref(system, i) for i in row["component_ids"]],
    }
    if full:
        view |= {"note": row["note"], "created_by": row["created_by"], "created_at": row["created_at"]}
    return view


def flag_row(system: System, row: Any) -> dict[str, Any]:
    """A flag in the Admin list: everything, with its components' ids."""
    return flag_view(system, row, full=True) | {
        "component_ids": list(row["component_ids"]),
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
        "removed_by": row["removed_by"],
        "removed_at": row["removed_at"],
    }


def audit_view(
    system: System, comp_ids: list[int], start: datetime, end: datetime, reason: str, note: str
) -> dict[str, Any]:
    refs = [_component_ref(system, i) for i in sorted(comp_ids)]
    return {
        "components": [f"{r['site']}:{r['type']}" for r in refs],
        "start": start,
        "end": end,
        "reason": reason,
        "note": note,
    }


# ------------------------------------------------------------------------------------------ public
@router.get("/systems/{code}/flags")
async def list_flags(
    request: Request,
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    scope: str | None = Query(None, pattern=r"^(site:[a-z0-9-]+|component:[a-z0-9-]+:[A-Z0-9]+)$"),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """Active flags overlapping a period, oldest first (FR-DQ-007): a chart window, a day, a site or everything."""
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_LIST_SPAN)
    params: dict[str, Any] = {"sys": system.id, "a": start, "b": end}
    where = ""
    if scope:
        kind, _, rest = scope.partition(":")
        slug, _, type_code = rest.partition(":")
        site = system.site_by_slug(slug)
        ids = [c.id for c in site.components if kind == "site" or c.type_code == type_code] if site else []
        if not ids:
            raise ApiError(404, "scope_not_found", f"unknown scope {scope!r}")
        params["ids"] = ids
        where = "AND EXISTS (SELECT 1 FROM flag_component x WHERE x.flag_id = f.id AND x.component_id = ANY(:ids))"
    rows = (
        await conn.execute(
            text(
                FLAG_SELECT
                + f"""WHERE f.system_id = :sys AND f.removed_at IS NULL AND f.end_at > :a AND f.start_at < :b {where}
                GROUP BY f.id ORDER BY f.start_at, f.id LIMIT 500"""
            ),
            params,
        )
    ).mappings()
    user = await principal(request)
    full = user is not None and not user.must_change_password
    return [flag_view(system, r, full=full) for r in rows]


# ------------------------------------------------------------------------------------------ Admin
async def _fetch(conn: AsyncConnection, system: System, flag_id: int) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                text(FLAG_SELECT + "WHERE f.id = :id AND f.system_id = :sys GROUP BY f.id"),
                {"id": flag_id, "sys": system.id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def _write_components(conn: AsyncConnection, flag_id: int, draft: Draft) -> None:
    """The flag's components and its invalidating intervals, replacing what was there."""
    await conn.execute(text("DELETE FROM flag_component WHERE flag_id = :id"), {"id": flag_id})
    await conn.execute(
        text("DELETE FROM invalid_interval WHERE source = 'flag' AND source_id = :id"), {"id": flag_id}
    )
    rows = [{"id": flag_id, "c": c.id, "a": draft.start, "b": draft.end} for c in draft.components]
    await conn.execute(text("INSERT INTO flag_component (flag_id, component_id) VALUES (:id, :c)"), rows)
    await conn.execute(
        text("""
        INSERT INTO invalid_interval (component_id, during, source, source_id)
        VALUES (:c, tstzrange(:a, :b, '[)'), 'flag', :id)
    """),
        rows,
    )


@admin_router.get("/flags")
async def admin_flags(system: str = DEFAULT_SYSTEM, removed: bool = False) -> list[dict[str, Any]]:
    """Every flag of the system, newest first; removed ones only when asked for."""
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        rows = (
            await conn.execute(
                text(
                    FLAG_SELECT
                    + f"""WHERE f.system_id = :sys {"" if removed else "AND f.removed_at IS NULL"}
                    GROUP BY f.id ORDER BY f.start_at DESC, f.id DESC LIMIT 1000"""
                ),
                {"sys": sy.id},
            )
        ).mappings()
        return [flag_row(sy, r) for r in rows]


@admin_router.get("/flags/preview")
async def preview_flag(
    system: str = DEFAULT_SYSTEM,
    components: str = Query("", pattern=r"^[0-9,]*$"),
    from_: str = Query(alias="from"),
    to: str = Query(),
    exclude: int | None = None,
) -> dict[str, Any]:
    """What a flag would change, per component: valid minutes in the range that would count as lost.

    ``exclude`` leaves out the flag being edited, so the effect shown is that of the edited flag on its own.
    """
    start, end = parse_period(from_, to, max_span=MAX_PREVIEW_SPAN)
    now = datetime.now(UTC)
    ids = list(dict.fromkeys(int(i) for i in components.split(",") if i))
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        by_id = {c.id: c for s in sy.sites for c in s.components}
        a, b = engine.clip_period(sy, start, end, now, await engine.grace_minutes(conn))
        out = []
        for cid in ids:
            c = by_id.get(cid)
            if c is None or c.is_dcp:
                continue
            wa, wb = engine.component_window(c, a, b)
            expected = minutes_between(wa, wb)
            valid = 0
            if expected > 0:
                params: dict[str, Any] = {"a": wa, "b": wb}
                invalid = await engine.invalid_intervals(conn, [c.id], wa, wb, exclude_flag=exclude)
                cond = engine.component_condition(sy, c, params, invalid)
                valid = int(
                    (
                        await conn.execute(
                            text(
                                f"SELECT count(*) FILTER (WHERE {cond}) FROM {engine.MINUTE_TABLE[sy.type_code]} "
                                f"WHERE site_id = {int(c.site_id)} AND time >= :a AND time < :b"
                            ),
                            params,
                        )
                    ).scalar_one()
                )
            out.append(
                {
                    "id": c.id,
                    **_component_ref(sy, c.id),
                    "minutes": max(expected, 0),
                    "lost": valid,
                    "already": max(expected, 0) - valid,
                }
            )
    days = flag_days(start, end, sy.coverage_start.date(), now.date())
    return {
        "start": start,
        "end": end,
        "components": out,
        "days": {"from": days[0], "to": days[1]} if days else None,
    }


@admin_router.post("/flags", status_code=201)
async def create_flag(
    body: FlagBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with get_engine().begin() as conn:
        sy = await _system(conn, body.system)
        d = check_flag(sy, body, now)
        flag_id = (
            await conn.execute(
                text("""
            INSERT INTO flag (system_id, start_at, end_at, reason, note, created_by)
            VALUES (:sys, :a, :b, :reason, :note, :by) RETURNING id
        """),
                {
                    "sys": sy.id,
                    "a": d.start,
                    "b": d.end,
                    "reason": d.reason,
                    "note": d.note,
                    "by": admin.username,
                },
            )
        ).scalar_one()
        await _write_components(conn, flag_id, d)
        await audit.record(
            conn,
            "flag_created",
            actor=admin.username,
            entity_type="flag",
            entity_id=str(flag_id),
            after=audit_view(sy, [c.id for c in d.components], d.start, d.end, d.reason, d.note),
            source_ip=client_ip(request),
        )
        days = flag_days(d.start, d.end, sy.coverage_start.date(), _today())
        job = await _enqueue(conn, "recompute", sy.code, *days, admin.username) if days else None
        row = await _fetch(conn, sy, flag_id)
    assert row is not None
    return {"flag": flag_row(sy, row), "job": job}


async def _locked(conn: AsyncConnection, flag_id: int) -> tuple[System, dict[str, Any]]:
    """The flag, locked for this transaction, with its system; 404 or 409 when it cannot be changed."""
    code = (
        await conn.execute(
            text("""
        SELECT sy.code FROM flag f JOIN system sy ON sy.id = f.system_id WHERE f.id = :id FOR UPDATE OF f
    """),
            {"id": flag_id},
        )
    ).scalar_one_or_none()
    if code is None:
        raise ApiError(404, "flag_not_found", "no such flag")
    sy = await _system(conn, code)
    row = await _fetch(conn, sy, flag_id)
    assert row is not None
    if row["removed_at"] is not None:
        raise ApiError(409, "flag_removed", "the flag was removed")
    return sy, row


@admin_router.patch("/flags/{flag_id}")
async def update_flag(
    flag_id: int, body: FlagBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Replaces a flag's components, range, reason and note."""
    now = datetime.now(UTC)
    async with get_engine().begin() as conn:
        sy, old = await _locked(conn, flag_id)
        d = check_flag(sy, body, now)
        before = audit_view(
            sy, old["component_ids"], old["start_at"], old["end_at"], old["reason"], old["note"]
        )
        after = audit_view(sy, [c.id for c in d.components], d.start, d.end, d.reason, d.note)
        job = None
        if before != after:
            await conn.execute(
                text("""
                UPDATE flag SET start_at = :a, end_at = :b, reason = :reason, note = :note,
                                updated_by = :by, updated_at = now()
                WHERE id = :id
            """),
                {
                    "id": flag_id,
                    "a": d.start,
                    "b": d.end,
                    "reason": d.reason,
                    "note": d.note,
                    "by": admin.username,
                },
            )
            await _write_components(conn, flag_id, d)
            changed_before, changed_after = audit.diff(before, after)
            await audit.record(
                conn,
                "flag_updated",
                actor=admin.username,
                entity_type="flag",
                entity_id=str(flag_id),
                before=changed_before,
                after=changed_after,
                source_ip=client_ip(request),
            )
            coverage, today = sy.coverage_start.date(), _today()
            # Only the reason or note changed: the figures stay as they are.
            if (before["components"], before["start"], before["end"]) != (
                after["components"],
                after["start"],
                after["end"],
            ):
                days = union_days(
                    flag_days(old["start_at"], old["end_at"], coverage, today),
                    flag_days(d.start, d.end, coverage, today),
                )
                if days:
                    job = await _enqueue(conn, "recompute", sy.code, *days, admin.username)
        row = await _fetch(conn, sy, flag_id)
    assert row is not None
    return {"flag": flag_row(sy, row), "job": job}


@admin_router.delete("/flags/{flag_id}")
async def remove_flag(
    flag_id: int, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Removes a flag: its minutes count as before. The flag itself stays, marked removed, and in the audit log."""
    async with get_engine().begin() as conn:
        sy, old = await _locked(conn, flag_id)
        await conn.execute(
            text("UPDATE flag SET removed_by = :by, removed_at = now() WHERE id = :id"),
            {"id": flag_id, "by": admin.username},
        )
        await conn.execute(
            text("DELETE FROM invalid_interval WHERE source = 'flag' AND source_id = :id"), {"id": flag_id}
        )
        await audit.record(
            conn,
            "flag_removed",
            actor=admin.username,
            entity_type="flag",
            entity_id=str(flag_id),
            before=audit_view(
                sy, old["component_ids"], old["start_at"], old["end_at"], old["reason"], old["note"]
            ),
            source_ip=client_ip(request),
        )
        days = flag_days(old["start_at"], old["end_at"], sy.coverage_start.date(), _today())
        job = await _enqueue(conn, "recompute", sy.code, *days, admin.username) if days else None
        row = await _fetch(conn, sy, flag_id)
    assert row is not None
    return {"flag": flag_row(sy, row), "job": job}
