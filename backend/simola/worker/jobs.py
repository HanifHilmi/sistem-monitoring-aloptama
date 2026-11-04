"""Persistent jobs (FR-ING-010, FR-ADM-002): reprocess and recompute. Claimed with SKIP LOCKED."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.core.timeutil import iter_days
from simola.ingestion.cat3 import Cat3Ingestor
from simola.kpi.engine import recompute_days
from simola.registry import System

logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


async def enqueue(engine: AsyncEngine, job_type: str, params: dict[str, Any], created_by: str = "cli") -> int:
    async with engine.begin() as conn:
        job_id = (
            await conn.execute(
                text(
                    "INSERT INTO job (type, params, created_by) VALUES (:t, CAST(:p AS jsonb), :by) RETURNING id"
                ),
                {"t": job_type, "p": json.dumps(params), "by": created_by},
            )
        ).scalar_one()
    return int(job_id)


async def claim(engine: AsyncEngine) -> dict[str, Any] | None:
    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text("""
            UPDATE job SET status = 'running', started_at = now()
            WHERE id = (SELECT id FROM job WHERE status = 'queued' ORDER BY created_at
                        FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING id, type, params
        """)
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def mark_interrupted(engine: AsyncEngine) -> int:
    """At worker start, running jobs from a previous process are marked interrupted (PRD §8.6 E13)."""
    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                "UPDATE job SET status = 'interrupted', finished_at = now(), "
                "message = 'worker restarted; re-run the job (it is idempotent)' WHERE status = 'running'"
            )
        )
    return int(res.rowcount or 0)


class JobContext:
    def __init__(self, engine: AsyncEngine, job_id: int) -> None:
        self.engine = engine
        self.job_id = job_id

    async def progress(self, fraction: float, line: str | None = None) -> None:
        async with self.engine.begin() as conn:
            status = (
                await conn.execute(
                    text(
                        "UPDATE job SET progress = :p, log = CASE WHEN CAST(:l AS text) IS NULL THEN log ELSE log || CAST(:l AS text) || E'\\n' END "
                        "WHERE id = :id RETURNING status"
                    ),
                    {"p": max(0.0, min(1.0, fraction)), "l": line, "id": self.job_id},
                )
            ).scalar_one()
        if status == "cancelled":
            raise JobCancelled

    async def finish(self, status: str, message: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE job SET status = :s, message = :m, finished_at = now(), "
                    "progress = CASE WHEN :s = 'done' THEN 1 ELSE progress END "
                    "WHERE id = :id AND status = 'running'"
                ),
                {"s": status, "m": message[:1000], "id": self.job_id},
            )


def _days(params: dict[str, Any]) -> list[date]:
    start = date.fromisoformat(params["from"])
    end = date.fromisoformat(params["to"])
    if end < start:
        raise ValueError("to must not be before from")
    return list(iter_days(start, end))


async def run_reprocess(ctx: JobContext, ingestor: Cat3Ingestor, params: dict[str, Any]) -> str:
    days = _days(params)
    newest_first = list(reversed(days))  # recent data first, so dashboards become useful early
    total_minutes = 0
    for i, d in enumerate(newest_first, start=1):
        summary = await ingestor.reprocess_day(d)
        mins = {k: v.get("minutes", 0) for k, v in summary["cdps"].items()}
        total_minutes += sum(mins.values())
        await ctx.progress(
            i / (len(newest_first) + 1),
            f"{d.isoformat()} "
            + " ".join(
                f"{k}={'no-file' if not v.get('file') else v['minutes']}" for k, v in summary["cdps"].items()
            ),
        )
    async with ingestor.engine.begin() as conn:
        stored = await recompute_days(conn, ingestor.system, days, datetime.now(UTC))
        await conn.execute(
            text("DELETE FROM rollup_dirty WHERE system_id = :s AND day = ANY(:d)"),
            {"s": ingestor.system.id, "d": days},
        )
    return f"reprocessed {len(days)} day(s), {total_minutes} CDP-minutes; {stored} daily rollup(s) stored"


async def run_recompute(ctx: JobContext, engine: AsyncEngine, system: System, params: dict[str, Any]) -> str:
    days = _days(params)
    stored = 0
    for i in range(0, len(days), 7):
        chunk = days[i : i + 7]
        async with engine.begin() as conn:
            stored += await recompute_days(conn, system, chunk, datetime.now(UTC))
        await ctx.progress((i + len(chunk)) / len(days), f"{chunk[0]}..{chunk[-1]}")
    return f"recomputed {stored} day(s)"


async def execute(
    engine: AsyncEngine, job: dict[str, Any], ingestor_for: Callable[[str], Awaitable[Cat3Ingestor]]
) -> None:
    ctx = JobContext(engine, job["id"])
    params = job["params"] if isinstance(job["params"], dict) else json.loads(job["params"])
    logger.info("job started", extra={"job_id": job["id"], "type": job["type"]})
    try:
        ingestor = await ingestor_for(params["system"])
        if job["type"] == "reprocess":
            message = await run_reprocess(ctx, ingestor, params)
        elif job["type"] == "recompute":
            message = await run_recompute(ctx, engine, ingestor.system, params)
        else:
            raise ValueError(f"unsupported job type {job['type']}")
        await ctx.finish("done", message)
        logger.info("job done", extra={"job_id": job["id"], "result": message})
    except JobCancelled:
        logger.info("job cancelled", extra={"job_id": job["id"]})
    except Exception as exc:
        logger.exception("job failed", extra={"job_id": job["id"]})
        await ctx.finish("failed", f"{type(exc).__name__}: {exc}")


def default_history_range(system: System, today: date) -> dict[str, str]:
    return {
        "system": system.code,
        "from": system.coverage_start.date().isoformat(),
        "to": (today - timedelta(days=0)).isoformat(),
    }
