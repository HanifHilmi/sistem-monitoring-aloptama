"""Viewer-level diagnostics (FR-ADM-004): signed-in Viewers and Admins only (R2.1). It is the only place
infrastructure details appear."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.api.deps import systems
from simola.api.security import require_viewer
from simola.core.config import get_settings
from simola.core.db import connection
from simola.kpi import status

router = APIRouter(prefix="/api/v1/internal", tags=["internal"], dependencies=[Depends(require_viewer)])


@router.get("/health")
async def internal_health(conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(UTC)
    workers = (
        (
            await conn.execute(
                text("SELECT worker, version, leader, last_beat FROM worker_heartbeat ORDER BY worker")
            )
        )
        .mappings()
        .all()
    )
    backups = (
        (
            await conn.execute(
                text(
                    "SELECT started_at, finished_at, ok, size_bytes, file_name, message FROM backup_run "
                    "ORDER BY started_at DESC LIMIT 5"
                )
            )
        )
        .mappings()
        .all()
    )
    jobs = (
        (
            await conn.execute(
                text(
                    "SELECT id, type, status, progress, message, created_at, started_at, finished_at FROM job "
                    "ORDER BY id DESC LIMIT 10"
                )
            )
        )
        .mappings()
        .all()
    )
    db_size = (await conn.execute(text("SELECT pg_database_size(current_database())"))).scalar_one()
    systems_out = []
    for system in await systems(conn):
        st = await status.system_status(conn, system, now)
        systems_out.append(
            {
                "code": system.code,
                "ingestion": [
                    {
                        **{k: v for k, v in src.items() if not k.startswith("_")},
                        "last_error": src["_error"],
                        "path": settings.cdp_paths.get(src["cdp"] or ""),
                    }
                    for src in st["ingestion"]
                ],
                **{
                    f"{kind}_files": [
                        {
                            **src,
                            "path": f"{settings.cdp_paths[src['cdp']]}/{folder}"
                            if src["cdp"] in settings.cdp_paths
                            else None,
                        }
                        for src in await status.file_sources(conn, system, now, f"{kind}s")
                    ]
                    for kind, folder in (("alarm", "alarm"), ("report", "reports"))
                },
                "cdps": [{**c, "address": settings.cdp_addresses.get(c["code"])} for c in st["cdps"]],
            }
        )
    return {
        "generated_at": now,
        "version": settings.version,
        "environment": settings.environment,
        "probe_method": "tcp:" + ",".join(str(p) for p in settings.probe_ports),
        "workers": [dict(w) for w in workers],
        "database": {"size_bytes": int(db_size)},
        "backups": [dict(b) for b in backups],
        "jobs": [dict(j) for j in jobs],
        "systems": systems_out,
    }
