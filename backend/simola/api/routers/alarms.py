"""AWOS alarms (R3.1: FR-ALM-001…004, FR-ING-008).

- The alarm list and history are for signed-in users (PRD §5.4, OPEN-13): messages can name the station's
  equipment and network. The public sees only the number of active alarms, in the Problems panel.
- Admins place each alarm name on a site or sensor (E12). The change is audited and applies to the whole history.
- SIMOLA never acknowledges an alarm: that is done on the AWOS.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola import alarms
from simola.api.deps import ApiError, parse_period, system_or_404
from simola.api.routers.admin_ops import DEFAULT_SYSTEM, _system
from simola.api.security import client_ip, csrf, require_admin, require_viewer
from simola.auth import audit
from simola.auth.sessions import Principal
from simola.core.db import connection, get_engine
from simola.registry import System

router = APIRouter(prefix="/api/v1", tags=["alarms"], dependencies=[Depends(require_viewer)])
admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin), Depends(csrf)]
)

MAX_HISTORY_SPAN = timedelta(days=366)
SCOPE = r"^(station|unmapped|site:[a-z0-9-]+|component:[a-z0-9-]+:[A-Z0-9]+)$"


def _scope(system: System, scope: str | None) -> str | None:
    """Refuses a site or sensor the system does not have."""
    if not scope or scope in ("station", "unmapped"):
        return scope
    kind, _, rest = scope.partition(":")
    slug, _, comp = rest.partition(":")
    site = system.site_by_slug(slug)
    if site is None or (kind == "component" and not any(c.type_code == comp for c in site.components)):
        raise ApiError(404, "scope_not_found", f"unknown scope {scope!r}")
    return scope


@router.get("/systems/{code}/alarms/active")
async def active_alarms(
    code: str,
    scope: str | None = Query(None, pattern=SCOPE),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    return await alarms.current(conn, system, datetime.now(UTC), _scope(system, scope))


@router.get("/systems/{code}/alarms")
async def alarm_history(
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    type: Literal["error", "warning"] | None = None,
    scope: str | None = Query(None, pattern=SCOPE),
    name: str | None = Query(None, max_length=100),
    active: bool | None = None,
    order: Literal["asc", "desc"] = "desc",
    offset: int = Query(0, ge=0, le=100_000),
    limit: int = Query(50, ge=1, le=200),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_HISTORY_SPAN)
    f = alarms.HistoryFilter(
        start, end, type, _scope(system, scope), (name or "").strip() or None, active, order
    )
    return await alarms.history(conn, system, f, offset=offset, limit=limit)


# ------------------------------------------------------------------------------------------ Admin mapping
class PlaceBody(BaseModel):
    kind: Literal["component", "site", "station", "unmapped"]
    site: str | None = None
    component: str | None = None


@admin_router.get("/alarm-names")
async def alarm_names(system: str = DEFAULT_SYSTEM) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        return await alarms.names(conn, await _system(conn, system))


@admin_router.put("/alarm-names/{name}")
async def save_alarm_name(
    name: str,
    body: PlaceBody,
    request: Request,
    system: str = DEFAULT_SYSTEM,
    admin: Principal = Depends(require_admin),
) -> dict[str, Any]:
    async with get_engine().begin() as conn:
        sy = await _system(conn, system)
        row = (
            (
                await conn.execute(
                    text("""
                SELECT place_kind, site_id, component_type FROM alarm_name
                WHERE system_id = :s AND name = :n FOR UPDATE
            """),
                    {"s": sy.id, "n": name},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ApiError(404, "alarm_not_found", "no alarm of that name has been seen")
        try:
            place = alarms.resolve_place(sy, body.kind, body.site, body.component)
        except alarms.PlaceError as exc:
            raise ApiError(422, exc.code, exc.code.replace("_", " ")) from exc
        before = alarms.place_view(sy, row["place_kind"], row["site_id"], row["component_type"])
        after = alarms.place_view(sy, place.kind, place.site_id, place.component_type)
        if before != after:
            await conn.execute(
                text("""
                UPDATE alarm_name SET place_kind = :k, site_id = :site, component_type = :c, source = 'admin',
                       updated_by = :by, updated_at = now()
                WHERE system_id = :s AND name = :n
            """),
                {
                    "k": place.kind,
                    "site": place.site_id,
                    "c": place.component_type,
                    "by": admin.username,
                    "s": sy.id,
                    "n": name,
                },
            )
            await audit.record(
                conn,
                "alarm_mapping_changed",
                actor=admin.username,
                entity_type="alarm",
                entity_id=name,
                before={"place": alarms.place_code(before)},
                after={"place": alarms.place_code(after)},
                source_ip=client_ip(request),
            )
        saved = next((n for n in await alarms.names(conn, sy) if n["name"] == name), None)
    if saved is None:  # a name is only stored with its first row, so this does not happen
        raise ApiError(404, "alarm_not_found", "no alarm of that name has been seen")
    return saved
