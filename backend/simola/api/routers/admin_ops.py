"""Admin operations API (R2.2): jobs (FR-ADM-002), settings (FR-ADM-003), mandatory fields (FR-REG-003) and
in-service periods (FR-REG-006). Every route needs an Admin; every change needs the CSRF header, is audited in its
transaction, and (for rules) queues the recompute that brings the figures in line.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.api.deps import ApiError, clear_registry_cache
from simola.api.security import client_ip, csrf, require_admin
from simola.auth import audit
from simola.auth.sessions import Principal
from simola.core.db import get_engine
from simola.core.timeutil import floor_minute, minutes_between
from simola.kpi import engine
from simola.registry import Component, System, load_system
from simola.worker import jobs

router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin), Depends(csrf)]
)

DEFAULT_SYSTEM = "WIDN-CAT3"
JOB_COLUMNS = "id, type, params, status, progress, message, created_by, created_at, started_at, finished_at"


async def _system(conn: AsyncConnection, code: str) -> System:
    system = await load_system(conn, code)
    if system is None:
        raise ApiError(404, "system_not_found", f"unknown system {code!r}")
    return system


def _today() -> date:
    return datetime.now(UTC).date()


def _json(value: Any) -> Any:
    """JSON columns as Python values, whichever way the driver hands them over."""
    return json.loads(value) if isinstance(value, str) else value


def _job(row: Any) -> dict[str, Any]:
    out = dict(row)
    out["params"] = _json(out["params"])
    return out


async def _bump_registry(conn: AsyncConnection) -> None:
    """Tells the worker to reload the registry (mandatory fields, in-service periods) before its next rollup."""
    await conn.execute(
        text("""
        INSERT INTO setting (key, value, updated_by) VALUES ('registry_version', '1', 'system')
        ON CONFLICT (key) DO UPDATE SET value = to_jsonb((setting.value #>> '{}')::int + 1), updated_at = now()
    """)
    )


async def _enqueue(
    conn: AsyncConnection,
    job_type: str,
    system: str,
    start: date,
    end: date,
    by: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(f"""
            INSERT INTO job (type, params, created_by) VALUES (:t, CAST(:p AS jsonb), :by) RETURNING {JOB_COLUMNS}
        """),
                {
                    "t": job_type,
                    "p": json.dumps(
                        {"system": system, "from": start.isoformat(), "to": end.isoformat(), **(extra or {})}
                    ),
                    "by": by,
                },
            )
        )
        .mappings()
        .one()
    )
    return _job(row)


# ------------------------------------------------------------------------------------------ jobs


class NewJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["reprocess", "recompute"]
    system: str = DEFAULT_SYSTEM
    start: date = Field(alias="from")
    end: date = Field(alias="to")
    # reprocess only: which CDP files to read again (FR-ING-010); all of them when absent
    sources: list[Literal["minutes", "alarms", "reports"]] | None = None


@router.get("/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(text(f"SELECT {JOB_COLUMNS} FROM job ORDER BY id DESC LIMIT 100"))
        ).mappings()
        return [_job(r) for r in rows]


@router.get("/jobs/{job_id}")
async def get_job(job_id: int) -> dict[str, Any]:
    async with get_engine().connect() as conn:
        row = (
            (await conn.execute(text(f"SELECT {JOB_COLUMNS}, log FROM job WHERE id = :id"), {"id": job_id}))
            .mappings()
            .first()
        )
    if row is None:
        raise ApiError(404, "job_not_found", "no such job")
    return _job(row)


@router.post("/jobs", status_code=201)
async def start_job(
    body: NewJob, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    if body.start > body.end:
        raise ApiError(422, "invalid_period", "from must not be after to")
    if body.end > _today():
        raise ApiError(422, "future_days", "days in the future have no data yet")
    extra: dict[str, Any] = {}
    if body.type == "reprocess" and body.sources is not None:
        if not body.sources:
            raise ApiError(422, "no_sources", "choose at least one kind of file to read again")
        chosen = [x for x in jobs.SOURCES if x in body.sources]
        if len(chosen) < len(jobs.SOURCES):
            extra["sources"] = chosen
    try:
        async with get_engine().begin() as conn:
            system = await _system(conn, body.system)
            if body.start < system.coverage_start.date():
                raise ApiError(422, "before_coverage", f"data starts on {system.coverage_start.date()}")
            job = await _enqueue(conn, body.type, system.code, body.start, body.end, admin.username, extra)
            await audit.record(
                conn,
                "job_started",
                actor=admin.username,
                entity_type="job",
                entity_id=str(job["id"]),
                after={"type": body.type, "system": system.code, "from": body.start, "to": body.end, **extra},
                source_ip=client_ip(request),
            )
    except IntegrityError as exc:  # job_one_active_reprocess
        raise ApiError(409, "job_running", "a reprocess is already queued or running") from exc
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: int, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    async with get_engine().begin() as conn:
        row = (
            (
                await conn.execute(
                    text(f"""
            UPDATE job SET status = 'cancelled', finished_at = now()
            WHERE id = :id AND status IN ('queued', 'running') RETURNING {JOB_COLUMNS}
        """),
                    {"id": job_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ApiError(409, "job_not_active", "only queued or running jobs can be cancelled")
        await audit.record(
            conn,
            "job_cancelled",
            actor=admin.username,
            entity_type="job",
            entity_id=str(job_id),
            source_ip=client_ip(request),
        )
    return _job(row)


# ------------------------------------------------------------------------------------------ settings


class ColorThresholds(BaseModel):
    good: float = Field(gt=0, le=100)
    warning: float = Field(gt=0, le=100)

    @model_validator(mode="after")
    def _order(self) -> ColorThresholds:
        if self.good <= self.warning:
            raise ValueError("good must be above warning")
        return self


class ProblemThresholds(BaseModel):
    cdp_no_data_min: int = Field(ge=1, le=120)
    cdp_unreachable_min: int = Field(ge=1, le=120)
    site_no_data_min: int = Field(ge=1, le=120)
    field_missing_min: int = Field(ge=1, le=120)
    ingest_lag_min: int = Field(ge=1, le=120)


SETTING_TYPES: dict[str, TypeAdapter[Any]] = {
    "color_thresholds": TypeAdapter(ColorThresholds),
    "grace_minutes": TypeAdapter(int),
    "problem_thresholds": TypeAdapter(ProblemThresholds),
    "calibration_due_soon_days": TypeAdapter(int),
}
DEFAULTS: dict[str, Any] = {
    "color_thresholds": {"good": 99, "warning": 95},
    "grace_minutes": 3,
    "problem_thresholds": ProblemThresholds(
        cdp_no_data_min=2, cdp_unreachable_min=2, site_no_data_min=2, field_missing_min=5, ingest_lag_min=5
    ).model_dump(),
    "calibration_due_soon_days": 30,
}


# Whole-number settings and their ranges: 1.5 or "3" are refused rather than rounded.
STRICT_INTS: dict[str, tuple[int, int]] = {"grace_minutes": (1, 15), "calibration_due_soon_days": (1, 180)}


class SettingBody(BaseModel):
    value: Any


def validate_setting(key: str, value: Any) -> Any:
    """The value as stored, or ApiError 422 with the reason."""
    if key not in SETTING_TYPES:
        raise ApiError(404, "setting_not_found", f"unknown setting {key!r}")
    try:
        parsed = SETTING_TYPES[key].validate_python(value, strict=key in STRICT_INTS)
    except ValidationError as exc:
        raise ApiError(422, "invalid_setting", exc.errors()[0]["msg"]) from exc
    if key in STRICT_INTS and not STRICT_INTS[key][0] <= parsed <= STRICT_INTS[key][1]:
        lo, hi = STRICT_INTS[key]
        raise ApiError(422, "invalid_setting", f"whole numbers from {lo} to {hi}")
    return parsed.model_dump() if isinstance(parsed, BaseModel) else parsed


async def _settings(conn: AsyncConnection) -> dict[str, Any]:
    rows = (
        (
            await conn.execute(
                text("SELECT key, value, updated_at, updated_by FROM setting WHERE key = ANY(:k)"),
                {"k": list(SETTING_TYPES)},
            )
        )
        .mappings()
        .all()
    )
    stored = {r["key"]: r for r in rows}
    out: dict[str, Any] = {"changed": {}}
    for key in SETTING_TYPES:
        value = _json(stored[key]["value"]) if key in stored else DEFAULTS[key]
        if key == "problem_thresholds":  # only the thresholds the Problems panel uses
            value = {k: value.get(k, DEFAULTS[key][k]) for k in DEFAULTS[key]}
        out[key] = value
        if key in stored and stored[key]["updated_by"] != "system":
            out["changed"][key] = {"at": stored[key]["updated_at"], "by": stored[key]["updated_by"]}
    return out


@router.get("/settings")
async def get_settings_doc() -> dict[str, Any]:
    async with get_engine().connect() as conn:
        return await _settings(conn)


@router.put("/settings/{key}")
async def put_setting(
    key: str, body: SettingBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    value = validate_setting(key, body.value)
    async with get_engine().begin() as conn:
        current = (await _settings(conn))[key]
        stored = value
        if key == "problem_thresholds":  # keep keys the panel does not edit
            raw = _json(await conn.scalar(text("SELECT value FROM setting WHERE key = :k"), {"k": key})) or {}
            stored = {**raw, **value}
        await conn.execute(
            text("""
            INSERT INTO setting (key, value, updated_at, updated_by) VALUES (:k, CAST(:v AS jsonb), now(), :by)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by
        """),
            {"k": key, "v": json.dumps(stored), "by": admin.username},
        )
        if isinstance(value, dict):
            before, after = audit.diff(current, value)
        else:
            before, after = {key: current}, {key: value}
        if after:
            await audit.record(
                conn,
                "setting_changed",
                actor=admin.username,
                entity_type="setting",
                entity_id=key,
                before=before,
                after=after,
                source_ip=client_ip(request),
            )
        return await _settings(conn)


# ------------------------------------------------------------------------------------------ mandatory fields


def _names(en: str, id_: str) -> dict[str, str]:
    return {"en": en, "id": id_}


def _components_of(system: System, type_code: str) -> list[Component]:
    return [c for s in system.sites for c in s.components if c.type_code == type_code]


def check_mandatory(system: System, type_code: str, fields: list[str]) -> list[str]:
    """The proposed mandatory fields, in field order, or ApiError 422. Every component of the type must keep at
    least one mandatory field it reports at its site: the registry refuses to load otherwise."""
    comps = _components_of(system, type_code)
    if not comps:
        raise ApiError(404, "component_type_not_found", f"no {type_code!r} component in {system.code}")
    if comps[0].is_dcp:
        raise ApiError(422, "dcp_rule_fixed", "the DCP rule is not editable")
    known = {f for c in comps for f in c.fields}
    unknown = sorted(set(fields) - known)
    if unknown:
        raise ApiError(422, "unknown_field", f"not a field of {type_code}: {', '.join(unknown)}")
    if not fields:
        raise ApiError(422, "at_least_one", "at least one mandatory field")
    for c in comps:
        if not set(fields) & set(c.fields):
            site = next(s for s in system.sites if s.id == c.site_id)
            raise ApiError(
                422, "no_mandatory_at_site", f"{type_code} at {site.slug} would have no mandatory field"
            )
    order = {code: f.sort for code, f in system.fields.items()}
    return sorted(set(fields), key=lambda f: order.get(f, 0))


@router.get("/mandatory-fields")
async def list_mandatory(system: str = DEFAULT_SYSTEM) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        required = {
            (r["component_type_code"], r["field_code"])
            for r in (
                await conn.execute(
                    text(
                        "SELECT component_type_code, field_code FROM mandatory_field WHERE system_type_code = :t"
                    ),
                    {"t": sy.type_code},
                )
            ).mappings()
        }
    types: dict[str, dict[str, Any]] = {}
    for site in sy.sites:
        for c in site.components:
            t = types.setdefault(
                c.type_code,
                {"type": c.type_code, "name": _names(c.name_en, c.name_id), "is_dcp": c.is_dcp, "fields": []},
            )
            for f in c.fields:
                if all(x["code"] != f for x in t["fields"]):
                    meta = sy.fields[f]
                    t["fields"].append(
                        {
                            "code": f,
                            "name": _names(meta.name_en, meta.name_id),
                            "mandatory": (c.type_code, f) in required,
                        }
                    )
    for t in types.values():
        t["fields"].sort(key=lambda x: sy.fields[x["code"]].sort)
    return list(types.values())


@router.get("/mandatory-fields/{component_type}/preview")
async def preview_mandatory(
    component_type: str, system: str = DEFAULT_SYSTEM, fields: str = Query(default="")
) -> dict[str, Any]:
    """This month's availability of each component of the type, with the current and the proposed fields."""
    now = datetime.now(UTC)
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        proposed = check_mandatory(sy, component_type, [f for f in fields.split(",") if f])
        grace = await engine.grace_minutes(conn)
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        a, b = engine.clip_period(sy, month, now, now, grace)
        sites = []
        for c in _components_of(sy, component_type):
            site = next(s for s in sy.sites if s.id == c.site_id)
            new = replace(c, mandatory=tuple(f for f in c.fields if f in proposed))
            wa, wb = engine.component_window(c, a, b)
            expected = minutes_between(wa, wb) if wb > wa else 0
            counts = {"current": 0, "proposed": 0}
            if expected:
                params: dict[str, Any] = {"a": wa, "b": wb}
                flags = await engine.invalid_intervals(conn, [] if c.is_dcp else [c.id], wa, wb)
                current = engine.component_condition(sy, c, params, flags)
                changed = engine.component_condition(sy, new, params, flags)
                row = (
                    (
                        await conn.execute(
                            text(
                                f"SELECT count(*) FILTER (WHERE {current}) AS current, "
                                f"count(*) FILTER (WHERE {changed}) AS proposed "
                                f"FROM {engine.MINUTE_TABLE[sy.type_code]} "
                                f"WHERE site_id = {int(c.site_id)} AND time >= :a AND time < :b"
                            ),
                            params,
                        )
                    )
                    .mappings()
                    .one()
                )
                counts = {"current": int(row["current"]), "proposed": int(row["proposed"])}
            sites.append(
                {
                    "slug": site.slug,
                    "name": _names(site.name_en, site.name_id),
                    "current": engine.availability(counts["current"], expected),
                    "proposed": engine.availability(counts["proposed"], expected),
                }
            )
    return {"type": component_type, "from": a, "to": b, "sites": sites}


class MandatoryBody(BaseModel):
    system: str = DEFAULT_SYSTEM
    fields: list[str] = Field(max_length=20)


@router.put("/mandatory-fields/{component_type}")
async def put_mandatory(
    component_type: str, body: MandatoryBody, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Applies to every period (OPEN-12): replaces the type's mandatory fields and queues a full recompute."""
    async with get_engine().begin() as conn:
        sy = await _system(conn, body.system)
        proposed = check_mandatory(sy, component_type, body.fields)
        before = sorted(
            await conn.scalars(
                text("""
                SELECT field_code FROM mandatory_field
                WHERE system_type_code = :t AND component_type_code = :c FOR UPDATE
            """),
                {"t": sy.type_code, "c": component_type},
            )
        )
        await conn.execute(
            text("DELETE FROM mandatory_field WHERE system_type_code = :t AND component_type_code = :c"),
            {"t": sy.type_code, "c": component_type},
        )
        await conn.execute(
            text(
                "INSERT INTO mandatory_field (system_type_code, component_type_code, field_code) VALUES (:t, :c, :f)"
            ),
            [{"t": sy.type_code, "c": component_type, "f": f} for f in proposed],
        )
        await audit.record(
            conn,
            "mandatory_changed",
            actor=admin.username,
            entity_type="mandatory",
            entity_id=component_type,
            before={"fields": before},
            after={"fields": proposed},
            source_ip=client_ip(request),
        )
        await _bump_registry(conn)
        # A confirmed detection only counts against a field that is mandatory now (FR-DQ-005).
        from simola.dq.detect import sync_invalid

        await sync_invalid(conn, await _system(conn, sy.code))
        job = await _enqueue(conn, "recompute", sy.code, sy.coverage_start.date(), _today(), admin.username)
    clear_registry_cache()
    return {"job": job}


# ------------------------------------------------------------------------------------------ components


def _component_row(sy: System, c: Component) -> dict[str, Any]:
    site = next(s for s in sy.sites if s.id == c.site_id)
    return {
        "id": c.id,
        "site": site.slug,
        "site_name": _names(site.name_en, site.name_id),
        "type": c.type_code,
        "name": _names(c.name_en, c.name_id),
        "is_dcp": c.is_dcp,
        "in_service_from": c.in_service_from,
        "in_service_to": c.in_service_to,
    }


async def component_rows(conn: AsyncConnection, sy: System, comps: list[Component]) -> list[dict[str, Any]]:
    """Registry rows with each sensor's record and calibration status (R2.5, FR-REG-004/005)."""
    from simola import records

    ids = [c.id for c in comps]
    metas = await records.component_meta(conn, ids)
    cal = await records.summaries(conn, ids, _today(), await records.due_soon_days(conn))
    return [_component_row(sy, c) | {"meta": metas.get(c.id, {}), "calibration": cal[c.id]} for c in comps]


@router.get("/components")
async def list_components(system: str = DEFAULT_SYSTEM) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        sy = await _system(conn, system)
        return await component_rows(conn, sy, [c for s in sy.sites for c in s.components])


class ServicePatch(BaseModel):
    in_service_from: datetime | None = None
    in_service_to: datetime | None = None


def affected_days(
    old: tuple[datetime | None, datetime | None],
    new: tuple[datetime | None, datetime | None],
    coverage: date,
    today: date,
) -> tuple[date, date] | None:
    """UTC days whose expected minutes change when an in-service period moves from `old` to `new`."""
    edges: list[date] = []
    for i, open_end in (
        (0, coverage),
        (1, date.max),
    ):  # no start = since data began; no end = still in service
        if old[i] != new[i]:
            edges += [d.date() if d else open_end for d in (old[i], new[i])]
    if not edges:
        return None
    start, end = max(min(edges), coverage), min(max(edges), today)
    return (start, end) if start <= end else None


@router.patch("/components/{component_id}")
async def patch_component(
    component_id: int, body: ServicePatch, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    for k, v in list(changes.items()):
        if v is not None:
            if v.tzinfo is None:
                raise ApiError(422, "invalid_time", f"{k} needs a UTC offset")
            changes[k] = floor_minute(v.astimezone(UTC))
    async with get_engine().begin() as conn:
        row = (
            (
                await conn.execute(
                    text("""
            SELECT c.id, st.system_id, sy.code AS system_code, ct.is_dcp, c.in_service_from, c.in_service_to
            FROM component c JOIN site st ON st.id = c.site_id JOIN system sy ON sy.id = st.system_id
            JOIN component_type ct ON ct.code = c.type_code WHERE c.id = :id FOR UPDATE OF c
        """),
                    {"id": component_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ApiError(404, "component_not_found", "no such component")
        if row["is_dcp"]:
            raise ApiError(422, "dcp_has_no_period", "the DCP follows its site")
        old = (row["in_service_from"], row["in_service_to"])
        new = (changes.get("in_service_from", old[0]), changes.get("in_service_to", old[1]))
        if new[0] and new[1] and new[0] >= new[1]:
            raise ApiError(422, "invalid_period", "in service from must be before until")
        job = None
        if new != old:
            await conn.execute(
                text("UPDATE component SET in_service_from = :f, in_service_to = :t WHERE id = :id"),
                {"f": new[0], "t": new[1], "id": component_id},
            )
            sy = await _system(conn, row["system_code"])
            comp = next(c for s in sy.sites for c in s.components if c.id == component_id)
            site = next(s for s in sy.sites if s.id == comp.site_id)
            await audit.record(
                conn,
                "in_service_changed",
                actor=admin.username,
                entity_type="component",
                entity_id=f"{site.slug}:{comp.type_code}",
                before={"in_service_from": old[0], "in_service_to": old[1]},
                after={"in_service_from": new[0], "in_service_to": new[1]},
                source_ip=client_ip(request),
            )
            await _bump_registry(conn)
            days = affected_days(old, new, sy.coverage_start.date(), _today())
            if days:
                job = await _enqueue(conn, "recompute", sy.code, days[0], days[1], admin.username)
        sy = await _system(conn, row["system_code"])
        comp = next(c for s in sy.sites for c in s.components if c.id == component_id)
        out = (await component_rows(conn, sy, [comp]))[0]
    clear_registry_cache()
    return {"component": out, "job": job}
