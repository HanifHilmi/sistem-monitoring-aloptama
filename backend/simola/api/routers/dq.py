"""Validity rules and detections (R2.4, FR-DQ-001..005, OPEN-08).

- Everyone sees confirmed detections; suspect and rejected ones, notes and who decided are for signed-in users.
- Admins manage rules (each change a new version, audited, and a detection run over the history), review the
  queue, and confirm or reject detections singly or in bulk. A decision on a mandatory field's detection changes
  the invalidating intervals in the same transaction and queues a recompute of its days (FR-KPI-008).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.api.deps import ApiError, parse_period, system_or_404
from simola.api.routers.admin_ops import DEFAULT_SYSTEM, JOB_COLUMNS, _enqueue, _job, _system, _today
from simola.api.security import client_ip, csrf, principal, require_admin
from simola.auth import audit
from simola.auth.sessions import Principal
from simola.core.db import connection, get_engine
from simola.dq import detect, history
from simola.dq import rules as R
from simola.registry import Component, System

router = APIRouter(prefix="/api/v1", tags=["detections"])
admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin), Depends(csrf)]
)

MAX_LIST_SPAN = timedelta(days=366)
DRY_RUN_DAYS = 30

DETECTION_SELECT = """
    SELECT d.id, d.rule_id, d.rule_version, d.component_id, d.field_code, d.type, d.params, d.start_at, d.end_at,
           d.evidence, d.status, d.decided_by, d.decided_at, d.note
    FROM dq_detection d
"""


def _json(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def _components(system: System) -> dict[int, tuple[str, Component]]:
    return {c.id: (s.slug, c) for s in system.sites for c in s.components}


def detection_view(system: System, row: Any, *, full: bool) -> dict[str, Any]:
    slug, comp = _components(system).get(row["component_id"], ("?", None))
    view: dict[str, Any] = {
        "id": row["id"],
        "site": slug,
        "component": comp.type_code if comp else "?",
        "field": row["field_code"],
        "type": row["type"],
        "rule_id": row["rule_id"],
        "rule_version": row["rule_version"],
        "params": _json(row["params"]),
        "start": row["start_at"],
        "end": row["end_at"],
        "minutes": int((row["end_at"] - row["start_at"]).total_seconds() // 60),
        "status": row["status"],
        "mandatory": bool(comp and row["field_code"] in comp.mandatory),
        "evidence": _json(row["evidence"]),
    }
    if full:
        view |= {"decided_by": row["decided_by"], "decided_at": row["decided_at"], "note": row["note"]}
    return view


def _scope_ids(system: System, scope: str | None) -> list[int]:
    comps = [c for s in system.sites for c in s.components if not c.is_dcp]
    if not scope:
        return [c.id for c in comps]
    kind, _, rest = scope.partition(":")
    slug, _, type_code = rest.partition(":")
    site = system.site_by_slug(slug)
    ids = [c.id for c in (site.components if site else ()) if kind == "site" or c.type_code == type_code]
    if not ids:
        raise ApiError(404, "scope_not_found", f"unknown scope {scope!r}")
    return ids


# ------------------------------------------------------------------------------------------ public
@router.get("/systems/{code}/detections")
async def list_detections(
    request: Request,
    code: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    scope: str | None = Query(None, pattern=r"^(site:[a-z0-9-]+|component:[a-z0-9-]+:[A-Z0-9]+)$"),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """Detections overlapping a period, oldest first: confirmed for everyone, all of them for signed-in users."""
    system = await system_or_404(conn, code)
    start, end = parse_period(from_, to, max_span=MAX_LIST_SPAN)
    user = await principal(request)
    full = user is not None and not user.must_change_password
    rows = (
        await conn.execute(
            text(
                DETECTION_SELECT
                + f"""WHERE d.component_id = ANY(:ids) AND d.end_at > :a AND d.start_at < :b
                {"" if full else "AND d.status = 'confirmed'"} ORDER BY d.start_at, d.id LIMIT 1000"""
            ),
            {"ids": _scope_ids(system, scope), "a": start, "b": end},
        )
    ).mappings()
    return [detection_view(system, r, full=full) for r in rows]


async def pending_suspects(conn: AsyncConnection, system: System) -> int:
    ids = [c.id for s in system.sites for c in s.components]
    return int(
        await conn.scalar(
            text("SELECT count(*) FROM dq_detection WHERE status = 'suspect' AND component_id = ANY(:ids)"),
            {"ids": ids},
        )
        or 0
    )


# ------------------------------------------------------------------------------------------ rules
class RuleBody(BaseModel):
    system: str = DEFAULT_SYSTEM
    component_type: str = Field(max_length=20)
    field: str = Field(max_length=20)
    site: str | None = Field(default=None, max_length=40)
    type: str = Field(max_length=20)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


def check_rule(system: System, body: RuleBody) -> tuple[int | None, dict[str, Any]]:
    """(site id or None, normalized parameters), or ApiError 422 with a code the screens translate."""
    comps = [(s, c) for s in system.sites for c in s.components if c.type_code == body.component_type]
    if not comps or all(c.is_dcp for _, c in comps):
        raise ApiError(422, "component_type_not_found", "unknown component type")
    owners = [s for s, c in comps if body.field in c.fields]
    if not owners:
        raise ApiError(422, "unknown_field", "this component does not report this field")
    if system.fields[body.field].is_text or body.field in detect.SKIP_FIELDS:
        raise ApiError(422, "text_field", "rules work on numeric measurements only")
    site_id = None
    if body.site:
        site = next((s for s in owners if s.slug == body.site), None)
        if site is None:
            raise ApiError(422, "site_has_no_field", "that site does not report this field")
        site_id = site.id
    try:
        return site_id, R.normalize(body.type, body.params)
    except R.RuleError as exc:
        raise ApiError(422, exc.code, f"invalid rule: {exc.code}") from exc


def _mandatory(system: System, component_type: str, field_code: str) -> bool:
    return any(
        c.type_code == component_type and field_code in c.mandatory
        for s in system.sites
        for c in s.components
    )


def _slug(system: System, site_id: int | None) -> str | None:
    return next((s.slug for s in system.sites if s.id == site_id), None) if site_id is not None else None


def rule_view(system: System, r: R.RuleRow, suspects: int) -> dict[str, Any]:
    return {
        "id": r.id,
        "component_type": r.component_type,
        "field": r.field,
        "site": _slug(system, r.site_id),
        "type": r.type,
        "params": r.params,
        "enabled": r.enabled,
        "proposed": r.proposed,
        "version": r.version,
        "changed_by": r.created_by,
        "changed_at": r.created_at,
        "mandatory": _mandatory(system, r.component_type, r.field),
        "suspects": suspects,
    }


async def _suspect_counts(conn: AsyncConnection) -> dict[int, int]:
    rows = await conn.execute(
        text("SELECT rule_id, count(*) FROM dq_detection WHERE status = 'suspect' GROUP BY rule_id")
    )
    return {int(r[0]): int(r[1]) for r in rows}


async def _enqueue_detect(
    conn: AsyncConnection, system: System, by: str, rule_id: int | None = None
) -> dict[str, Any]:
    """A detection run over the whole history (FR-DQ-003: on a rule change, default full history)."""
    params: dict[str, Any] = {
        "system": system.code,
        "from": system.coverage_start.date().isoformat(),
        "to": _today().isoformat(),
    }
    if rule_id is not None:
        params["rule_id"] = rule_id
    row = (
        (
            await conn.execute(
                text(
                    f"INSERT INTO job (type, params, created_by) VALUES ('detect', CAST(:p AS jsonb), :by) "
                    f"RETURNING {JOB_COLUMNS}"
                ),
                {"p": json.dumps(params), "by": by},
            )
        )
        .mappings()
        .one()
    )
    return _job(row)


@admin_router.get("/rules")
async def list_rules(system: str = DEFAULT_SYSTEM) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        counts = await _suspect_counts(conn)
        rules = await detect.load_rules(conn, sy)
    return [rule_view(sy, r, counts.get(r.id, 0)) for r in rules]


@admin_router.get("/rules/history")
async def rule_history(component_type: str, field: str, system: str = DEFAULT_SYSTEM) -> dict[str, Any]:
    """The field's history and the starting values proposed from it (OPEN-08). Stored; refreshed weekly."""
    async with get_engine().begin() as conn:
        sy = await _system(conn, system)
        check_rule(
            sy, RuleBody(component_type=component_type, field=field, type="stuck", params={"minutes": 60})
        )
        return await history.field_history(conn, sy, component_type, field)


@admin_router.get("/rules/dry-run")
async def dry_run(
    component_type: str,
    field: str,
    type: str,
    params: str = Query(max_length=1000),
    site: str | None = None,
    system: str = DEFAULT_SYSTEM,
) -> dict[str, Any]:
    """What a draft rule would have raised over the last 30 days, before it is saved."""
    try:
        draft = json.loads(params)
    except json.JSONDecodeError as exc:
        raise ApiError(422, "invalid_params", "params must be JSON") from exc
    if not isinstance(draft, dict):
        raise ApiError(422, "invalid_params", "params must be an object")
    end = datetime.combine(_today(), datetime.min.time(), UTC)
    start = end - timedelta(days=DRY_RUN_DAYS)
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        body = RuleBody(component_type=component_type, field=field, site=site, type=type, params=draft)
        site_id, norm = check_rule(sy, body)
        lb = R.lookback(type, norm)
        examples: list[dict[str, Any]] = []
        minutes = 0
        hit_sites: set[str] = set()
        for s in sy.sites:
            if site_id is not None and s.id != site_id:
                continue
            if not any(c.type_code == component_type and field in c.fields for c in s.components):
                continue
            ms, vs = await detect.field_values(conn, sy, s.id, field, start - timedelta(minutes=lb), end)
            for h in R.apply(type, norm, ms, vs):
                if h.end <= detect.minute_no(start):
                    continue
                minutes += h.end - h.start
                hit_sites.add(s.slug)
                examples.append(
                    {
                        "site": s.slug,
                        "start": detect.at(h.start),
                        "end": detect.at(h.end),
                        "minutes": h.end - h.start,
                        "evidence": h.evidence,
                    }
                )
    examples.sort(key=lambda e: (-e["minutes"], -e["start"].timestamp()))
    return {
        "from": start,
        "to": end,
        "intervals": len(examples),
        "minutes": minutes,
        "sites": len(hit_sites),
        "examples": examples[:5],
    }


async def _rule_or_404(conn: AsyncConnection, sy: System, rule_id: int) -> R.RuleRow:
    rule = next((r for r in await detect.load_rules(conn, sy) if r.id == rule_id), None)
    if rule is None:
        raise ApiError(404, "rule_not_found", "no such rule")
    return rule


@admin_router.get("/rules/{rule_id}/versions")
async def rule_versions(rule_id: int, system: str = DEFAULT_SYSTEM) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        await _rule_or_404(conn, sy, rule_id)
        rows = (
            await conn.execute(
                text("""
            SELECT version, site_id, params, enabled, created_by, created_at FROM dq_rule_version
            WHERE rule_id = :id ORDER BY version DESC
        """),
                {"id": rule_id},
            )
        ).mappings()
        return [
            {
                "version": r["version"],
                "site": _slug(sy, r["site_id"]),
                "params": _json(r["params"]),
                "enabled": r["enabled"],
                "created_by": r["created_by"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def _conflict(rules: list[R.RuleRow], body: RuleBody, site_id: int | None, rule_id: int | None) -> bool:
    return any(
        r.id != rule_id
        and r.component_type == body.component_type
        and r.field == body.field
        and r.type == body.type
        and r.site_id == site_id
        for r in rules
    )


def _audit_rule(sy: System, site_id: int | None, params: dict[str, Any], enabled: bool) -> dict[str, Any]:
    return {"site": _slug(sy, site_id), "params": params, "enabled": enabled}


@admin_router.post("/rules", status_code=201)
async def create_rule(
    body: RuleBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    async with get_engine().begin() as conn:
        sy = await _system(conn, body.system)
        site_id, params = check_rule(sy, body)
        if _conflict(await detect.load_rules(conn, sy), body, site_id, None):
            raise ApiError(409, "rule_exists", "this field already has a rule of this kind for this scope")
        rule_id = await conn.scalar(
            text("""
            INSERT INTO dq_rule (system_id, component_type_code, field_code, type) VALUES (:s, :t, :f, :ty)
            RETURNING id
        """),
            {"s": sy.id, "t": body.component_type, "f": body.field, "ty": body.type},
        )
        await conn.execute(
            text("""
            INSERT INTO dq_rule_version (rule_id, version, site_id, params, enabled, created_by)
            VALUES (:id, 1, :site, CAST(:p AS jsonb), :on, :by)
        """),
            {
                "id": rule_id,
                "site": site_id,
                "p": json.dumps(params),
                "on": body.enabled,
                "by": admin.username,
            },
        )
        await audit.record(
            conn,
            "rule_created",
            actor=admin.username,
            entity_type="rule",
            entity_id=f"{rule_id} {body.component_type}:{body.field}:{body.type}",
            after=_audit_rule(sy, site_id, params, body.enabled),
            source_ip=client_ip(request),
        )
        job = await _enqueue_detect(conn, sy, admin.username, int(rule_id)) if body.enabled else None
        rule = await _rule_or_404(conn, sy, int(rule_id))
    return {"rule": rule_view(sy, rule, 0), "job": job}


@admin_router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int, body: RuleBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """A new version with the given scope, parameters and state; approving a proposed rule is a save too."""
    async with get_engine().begin() as conn:
        sy = await _system(conn, body.system)
        await conn.execute(text("SELECT id FROM dq_rule WHERE id = :id FOR UPDATE"), {"id": rule_id})
        rules = await detect.load_rules(conn, sy)
        old = next((r for r in rules if r.id == rule_id), None)
        if old is None:
            raise ApiError(404, "rule_not_found", "no such rule")
        body = body.model_copy(
            update={"component_type": old.component_type, "field": old.field, "type": old.type}
        )
        site_id, params = check_rule(sy, body)
        if _conflict(rules, body, site_id, rule_id):
            raise ApiError(409, "rule_exists", "this field already has a rule of this kind for this scope")
        before = _audit_rule(sy, old.site_id, old.params, old.enabled)
        after = _audit_rule(sy, site_id, params, body.enabled)
        job = None
        if before != after or old.proposed:
            await conn.execute(
                text("""
                INSERT INTO dq_rule_version (rule_id, version, site_id, params, enabled, created_by)
                VALUES (:id, :v, :site, CAST(:p AS jsonb), :on, :by)
            """),
                {
                    "id": rule_id,
                    "v": old.version + 1,
                    "site": site_id,
                    "p": json.dumps(params),
                    "on": body.enabled,
                    "by": admin.username,
                },
            )
            await conn.execute(text("UPDATE dq_rule SET proposed = false WHERE id = :id"), {"id": rule_id})
            changed_before, changed_after = audit.diff(before, after)
            await audit.record(
                conn,
                "rule_changed",
                actor=admin.username,
                entity_type="rule",
                entity_id=f"{rule_id} {old.component_type}:{old.field}:{old.type}",
                before=changed_before or {"proposed": True},
                after=changed_after or {"proposed": False},
                source_ip=client_ip(request),
            )
            if body.enabled:
                job = await _enqueue_detect(conn, sy, admin.username, rule_id)
        rule = await _rule_or_404(conn, sy, rule_id)
        counts = await _suspect_counts(conn)
    return {"rule": rule_view(sy, rule, counts.get(rule_id, 0)), "job": job}


# ------------------------------------------------------------------------------------------ review queue
Status = Literal["suspect", "confirmed", "rejected"]


@admin_router.get("/detections")
async def review_queue(
    system: str = DEFAULT_SYSTEM,
    status: Status = "suspect",
    site: str | None = None,
    component: str | None = None,
    field: str | None = None,
    type: str | None = None,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """The queue (suspects, newest first) or the decided ones (latest decision first), with counts per status."""
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        ids = [
            c.id
            for s in sy.sites
            for c in s.components
            if not c.is_dcp and (not site or s.slug == site) and (not component or c.type_code == component)
        ]
        where = ["d.component_id = ANY(:ids)"]
        params: dict[str, Any] = {"ids": ids, "off": offset, "lim": limit, "st": status}
        if field:
            where.append("d.field_code = :f")
            params["f"] = field
        if type:
            where.append("d.type = :t")
            params["t"] = type
        if from_:
            where.append("d.end_at > :a")
            params["a"] = datetime.combine(from_, datetime.min.time(), UTC)
        if to:
            where.append("d.start_at < :b")
            params["b"] = datetime.combine(to + timedelta(days=1), datetime.min.time(), UTC)
        cond = " AND ".join(where)
        counts = {s: 0 for s in R.STATUSES}
        for st, n in await conn.execute(
            text(f"SELECT d.status, count(*) FROM dq_detection d WHERE {cond} GROUP BY d.status"), params
        ):
            counts[st] = int(n)
        order = (
            "d.start_at DESC, d.id DESC" if status == "suspect" else "d.decided_at DESC NULLS LAST, d.id DESC"
        )
        rows = (
            await conn.execute(
                text(
                    DETECTION_SELECT
                    + f"WHERE {cond} AND d.status = :st ORDER BY {order} OFFSET :off LIMIT :lim"
                ),
                params,
            )
        ).mappings()
        return {
            "total": counts[status],
            "counts": counts,
            "detections": [detection_view(sy, r, full=True) for r in rows],
        }


class DecisionBody(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=200)
    decision: Literal["confirm", "reject"]
    note: str | None = Field(default=None, max_length=500)


@admin_router.post("/detections/decide")
async def decide(
    body: DecisionBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Confirms or rejects detections, or reverses an earlier decision (FR-DQ-004). Audited one by one."""
    ids = sorted(set(body.ids))
    if not ids:
        raise ApiError(422, "no_detections", "select at least one detection")
    status = "confirmed" if body.decision == "confirm" else "rejected"
    note = (body.note or "").strip() or None
    async with get_engine().begin() as conn:
        rows = (
            (
                await conn.execute(
                    text(DETECTION_SELECT + "WHERE d.id = ANY(:ids) ORDER BY d.id FOR UPDATE"), {"ids": ids}
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != len(ids):
            raise ApiError(404, "detection_not_found", "a detection no longer exists")
        code = await conn.scalar(
            text("""
            SELECT sy.code FROM component c JOIN site s ON s.id = c.site_id JOIN system sy ON sy.id = s.system_id
            WHERE c.id = :c
        """),
            {"c": rows[0]["component_id"]},
        )
        sy = await _system(conn, str(code))
        comps = _components(sy)
        if any(r["component_id"] not in comps for r in rows):
            raise ApiError(422, "mixed_systems", "decide the detections of one system at a time")
        first: date | None = None
        last: date | None = None
        for r in rows:
            if r["status"] == status:
                continue
            await conn.execute(
                text("""
                UPDATE dq_detection SET status = :st, decided_by = :by, decided_at = now(), note = :note,
                                        updated_at = now()
                WHERE id = :id
            """),
                {"st": status, "by": admin.username, "note": note, "id": r["id"]},
            )
            await audit.record(
                conn,
                "detections_decided",
                actor=admin.username,
                entity_type="detection",
                entity_id=str(r["id"]),
                before={"status": r["status"]},
                after={"status": status, **({"note": note} if note else {})},
                source_ip=client_ip(request),
            )
            mandatory = r["field_code"] in comps[r["component_id"]][1].mandatory
            if mandatory and "confirmed" in (status, r["status"]):
                a, b = r["start_at"].date(), (r["end_at"] - timedelta(minutes=1)).date()
                first = a if first is None or a < first else first
                last = b if last is None or b > last else last
        job = None
        if first is not None and last is not None:
            await detect.sync_invalid(conn, sy)
            start = max(first, sy.coverage_start.date())
            end = min(last, _today())
            if start <= end:
                job = await _enqueue(conn, "recompute", sy.code, start, end, admin.username)
        decided = (
            await conn.execute(text(DETECTION_SELECT + "WHERE d.id = ANY(:ids) ORDER BY d.id"), {"ids": ids})
        ).mappings()
        return {"decided": [detection_view(sy, r, full=True) for r in decided], "job": job}
