"""Current status and the Problems panel (FR-DSH-003/004/010, FR-ING-013).

Status vocabulary (UX-002): valid, field_missing, no_data, stale, not_in_service, unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.config import get_settings
from simola.core.timeutil import floor_minute
from simola.kpi.engine import MINUTE_TABLE, component_condition, grace_minutes
from simola.registry import Component, System, get_setting

LOOKBACK = timedelta(hours=6)
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}

DEFAULT_THRESHOLDS = {
    "cdp_no_data_min": 2,
    "cdp_unreachable_min": 2,
    "site_no_data_min": 2,
    "field_missing_min": 5,
    "ingest_lag_min": 5,
    "backup_overdue_h": 26,
}


@dataclass
class Thresholds:
    cdp_no_data_min: int
    cdp_unreachable_min: int
    site_no_data_min: int
    field_missing_min: int
    ingest_lag_min: int
    backup_overdue_h: int


async def thresholds(conn: AsyncConnection) -> Thresholds:
    raw = await get_setting(conn, "problem_thresholds", {}) or {}
    merged = {**DEFAULT_THRESHOLDS, **{k: int(v) for k, v in raw.items() if k in DEFAULT_THRESHOLDS}}
    return Thresholds(**merged)


def _in_service(comp: Component, now: datetime) -> bool:
    if comp.in_service_from is not None and now < comp.in_service_from:
        return False
    return not (comp.in_service_to is not None and now >= comp.in_service_to)


async def system_status(conn: AsyncConnection, system: System, now: datetime) -> dict[str, Any]:
    g = await grace_minutes(conn)
    th = await thresholds(conn)
    base = floor_minute(now)
    since = base - LOOKBACK

    # --- ingestion sources
    sources = (
        (
            await conn.execute(
                text("""
        SELECT i.source, n.code AS cdp, i.available, i.last_success_at, i.last_record_time, i.last_error,
               i.parse_warnings, i.oldest_file_date
        FROM ingest_status i LEFT JOIN cdp_node n ON n.id = i.cdp_id
        WHERE i.system_id = :s AND i.source LIKE :kind ORDER BY i.source
    """),
                {"s": system.id, "kind": "%:oneminute"},
            )
        )
        .mappings()
        .all()
    )
    ingest = []
    for r in sources:
        lag = (now - r["last_success_at"]).total_seconds() / 60 if r["last_success_at"] else None
        stale = lag is None or lag > th.ingest_lag_min
        ingest.append(
            {
                "cdp": r["cdp"],
                "available": r["available"],
                "stale": stale,
                "lag_min": round(lag, 1) if lag is not None else None,
                "last_record_time": r["last_record_time"],
                "parse_warnings": r["parse_warnings"],
                "oldest_file_date": r["oldest_file_date"],
                "_error": r["last_error"],
            }
        )
    ingestion_stale = not ingest or all(s["stale"] or not s["available"] for s in ingest)

    # --- CDPs
    cdp_rows = (
        (
            await conn.execute(
                text("""
        SELECT cdp_id, max(time) FILTER (WHERE data_flow) AS last_flow
        FROM cdp_minute_fact WHERE cdp_id = ANY(:ids) AND time >= :since GROUP BY cdp_id
    """),
                {"ids": [c.id for c in system.cdps], "since": since},
            )
        )
        .mappings()
        .all()
    )
    last_flow = {r["cdp_id"]: r["last_flow"] for r in cdp_rows}
    cdps = []
    for c in system.cdps:
        probes = (
            (
                await conn.execute(
                    text("""
            SELECT time, probes_attempted, probes_ok, rtt_min_ms FROM cdp_minute_fact
            WHERE cdp_id = :c AND probes_attempted > 0 AND time >= :lo AND time < :hi
            ORDER BY time DESC LIMIT :n
        """),
                    {"c": c.id, "lo": base - timedelta(minutes=10), "hi": base, "n": th.cdp_unreachable_min},
                )
            )
            .mappings()
            .all()
        )
        if not probes:
            reach = "unknown"
        elif len(probes) >= th.cdp_unreachable_min and all(p["probes_ok"] == 0 for p in probes):
            reach = "unreachable"
        else:
            reach = "reachable" if probes[0]["probes_ok"] > 0 else "degraded"
        lf = last_flow.get(c.id)
        if ingestion_stale:
            flow = "unknown"
        elif lf is not None and lf >= base - timedelta(minutes=g + th.cdp_no_data_min):
            flow = "producing"
        else:
            flow = "not_producing"
        cdps.append(
            {
                "code": c.code,
                "data_flow": flow,
                "last_data_minute": lf,
                "reachability": reach,
                "rtt_ms": probes[0]["rtt_min_ms"] if probes else None,
            }
        )

    # --- sites and components
    params: dict[str, Any] = {"since": since, "sites": [s.id for s in system.sites]}
    selects = [f"max(time) FILTER (WHERE site_id = {int(s.id)}) AS s{s.id}" for s in system.sites]
    comps = [c for s in system.sites for c in s.components]
    selects += [
        f"max(time) FILTER (WHERE {component_condition(system, c, params)}) AS c{c.id}" for c in comps
    ]
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {', '.join(selects)} FROM {MINUTE_TABLE[system.type_code]} "
                    "WHERE site_id = ANY(:sites) AND time >= :since"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    sites = []
    for s in system.sites:
        last_rec = row[f"s{s.id}"]
        site_no_data = last_rec is None or last_rec < base - timedelta(minutes=g + th.site_no_data_min)
        comp_out = []
        for comp in s.components:
            last_valid = row[f"c{comp.id}"]
            if not _in_service(comp, now):
                status = "not_in_service"
            elif ingestion_stale:
                status = "stale"
            elif site_no_data:
                status = "no_data"
            elif comp.is_dcp:
                ok = last_valid is not None and last_valid >= base - timedelta(
                    minutes=g + th.site_no_data_min
                )
                status = "valid" if ok else "no_data"
            else:
                ok = last_valid is not None and last_valid >= base - timedelta(
                    minutes=g + th.field_missing_min
                )
                status = "valid" if ok else "field_missing"
            comp_out.append(
                {
                    "type": comp.type_code,
                    "is_dcp": comp.is_dcp,
                    "status": status,
                    "last_valid_minute": last_valid,
                }
            )
        online = sum(1 for c in comp_out if c["status"] == "valid")
        sites.append(
            {
                "code": s.code,
                "slug": s.slug,
                "last_data_minute": last_rec,
                "no_data": site_no_data,
                "components_online": online,
                "components_total": len(comp_out),
                "components": comp_out,
            }
        )

    backup = (
        (
            await conn.execute(
                text(
                    "SELECT max(finished_at) FILTER (WHERE ok) AS last_ok, max(started_at) AS last_run FROM backup_run"
                )
            )
        )
        .mappings()
        .one()
    )

    return {
        "generated_at": now,
        "grace_minutes": g,
        "ingestion": ingest,
        "ingestion_stale": ingestion_stale,
        "cdps": cdps,
        "sites": sites,
        "last_data_minute": max(
            (s["last_data_minute"] for s in sites if s["last_data_minute"]), default=None
        ),
        "backup": {"last_ok": backup["last_ok"], "last_run": backup["last_run"]},
        "thresholds": th.__dict__,
    }


async def alarm_sources(conn: AsyncConnection, system: System, now: datetime) -> list[dict[str, Any]]:
    """The alarm file readers, one per CDP (R3.1), for the health page. An alarm file exists only on days with
    an alarm, so the last row may be days old: only the last successful read says whether the reader works."""
    th = await thresholds(conn)
    rows = (
        await conn.execute(
            text("""
        SELECT n.code AS cdp, i.available, i.last_success_at, i.last_record_time, i.last_error, i.parse_warnings
        FROM ingest_status i LEFT JOIN cdp_node n ON n.id = i.cdp_id
        WHERE i.system_id = :s AND i.source LIKE :kind ORDER BY i.source
    """),
            {"s": system.id, "kind": "%:alarms"},
        )
    ).mappings()
    out = []
    for r in rows:
        lag = (now - r["last_success_at"]).total_seconds() / 60 if r["last_success_at"] else None
        out.append(
            {
                "cdp": r["cdp"],
                "available": r["available"],
                "stale": lag is None or lag > th.ingest_lag_min,
                "lag_min": round(lag, 1) if lag is not None else None,
                "last_record_time": r["last_record_time"],
                "parse_warnings": r["parse_warnings"],
                "last_error": r["last_error"],
            }
        )
    return out


def problems_from_status(system: System, status: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Derive the Problems panel. Parameters are public-safe codes only (FR-AUTH-006)."""
    out: list[dict[str, Any]] = []
    sys_link = f"/systems/{system.code}"

    def add(code: str, severity: str, link: str, **params: Any) -> None:
        out.append({"code": code, "severity": severity, "link": link, "params": params})

    for src in status["ingestion"]:
        if not src["available"]:
            add("source_unavailable", "major", sys_link, cdp=src["cdp"])
        elif src["stale"]:
            add("ingest_stale", "major", sys_link, cdp=src["cdp"], lag_min=src["lag_min"])

    cdps = status["cdps"]
    not_producing = [c for c in cdps if c["data_flow"] == "not_producing"]
    all_down = bool(cdps) and len(not_producing) == len(cdps)
    if all_down:
        add("cdp_all_no_data", "critical", sys_link)
    else:
        for c in not_producing:
            add("cdp_no_data", "major", sys_link, cdp=c["code"], since=c["last_data_minute"])
    for c in cdps:
        if c["reachability"] == "unreachable":
            add("cdp_unreachable", "major", sys_link, cdp=c["code"])

    if not all_down and not status["ingestion_stale"]:
        for s in status["sites"]:
            link = f"{sys_link}/sites/{s['slug']}"
            if s["no_data"]:
                add("site_no_data", "major", link, site=s["code"], since=s["last_data_minute"])
                continue
            for comp in s["components"]:
                if comp["status"] == "field_missing":
                    add(
                        "component_field_missing",
                        "minor",
                        link,
                        site=s["code"],
                        component=comp["type"],
                        since=comp["last_valid_minute"],
                    )

    if get_settings().backup_expected:
        last_ok = status["backup"]["last_ok"]
        overdue_h = status["thresholds"]["backup_overdue_h"]
        if last_ok is None or now - last_ok > timedelta(hours=overdue_h):
            add("backup_overdue", "minor", "/internal/health", last_ok=last_ok)

    out.sort(key=lambda p: SEVERITY_ORDER[p["severity"]])
    return out
