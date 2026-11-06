"""Persistent jobs (FR-ING-010, FR-ADM-002): reprocess and recompute. Claimed with SKIP LOCKED."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.core.timeutil import DAY, day_start, iter_days
from simola.dq import detect
from simola.ingestion.cat3 import Cat3Ingestor
from simola.kpi.engine import recompute_days
from simola.registry import System, load_system

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


SOURCES = ("minutes", "alarms")  # which CDP files a reprocess reads again (FR-ING-010)


def reprocess_sources(params: dict[str, Any]) -> list[str]:
    """The sources a reprocess job reads; all of them when the job does not say."""
    chosen = params.get("sources") or SOURCES
    return [s for s in SOURCES if s in chosen]


async def run_reprocess(ctx: JobContext, ingestor: Cat3Ingestor, params: dict[str, Any]) -> str:
    days = _days(params)
    sources = reprocess_sources(params)
    newest_first = list(reversed(days))  # recent data first, so dashboards become useful early
    total_minutes = 0
    alarm_rows = 0
    for i, d in enumerate(newest_first, start=1):
        line = [d.isoformat()]
        if "minutes" in sources:
            summary = await ingestor.reprocess_day(d)
            mins = {k: v.get("minutes", 0) for k, v in summary["cdps"].items()}
            total_minutes += sum(mins.values())
            line += [
                f"{k}={'no-file' if not v.get('file') else v['minutes']}" for k, v in summary["cdps"].items()
            ]
        if "alarms" in sources:
            found_alarms = await ingestor.alarms.reprocess_day(d)
            alarm_rows += sum(v.get("new", 0) for v in found_alarms["cdps"].values())
            line += [
                f"alarms:{k}={'no-file' if not v.get('file') else v['rows']}"
                for k, v in found_alarms["cdps"].items()
            ]
        await ctx.progress(i / (len(newest_first) + 1), " ".join(line))
    alarms_note = f"{alarm_rows} new alarm row(s)"
    if "minutes" not in sources:
        # Alarms change no figure: nothing to check or recompute.
        return f"reprocessed {len(days)} day(s) of alarm files; {alarms_note}"
    # The minutes changed: the rules look at them again (FR-DQ-003), before the figures are recomputed.
    async with ingestor.engine.connect() as conn:
        system = await load_system(conn, ingestor.system.code) or ingestor.system
    found = await detect_range(ingestor.engine, system, days[0], days[-1])
    async with ingestor.engine.begin() as conn:
        stored = await recompute_days(conn, system, days, datetime.now(UTC))
        await conn.execute(
            text("DELETE FROM rollup_dirty WHERE system_id = :s AND day = ANY(:d)"),
            {"s": ingestor.system.id, "d": days},
        )
    message = f"reprocessed {len(days)} day(s), {total_minutes} CDP-minutes; {stored} daily rollup(s) stored; {found}"
    return message + (f"; {alarms_note}" if "alarms" in sources else "")


def month_chunks(first: date, last: date) -> list[tuple[date, date]]:
    """[first, last] cut at month ends, oldest first (a later chunk extends stretches the earlier one found)."""
    out: list[tuple[date, date]] = []
    a = first
    while a <= last:
        nxt = (a.replace(day=1) + timedelta(days=32)).replace(day=1)
        b = min(last, nxt - timedelta(days=1))
        out.append((a, b))
        a = b + timedelta(days=1)
    return out


async def detect_range(
    engine: AsyncEngine,
    system: System,
    first: date,
    last: date,
    *,
    rule_ids: list[int] | None = None,
    ctx: JobContext | None = None,
) -> str:
    """Runs the rules over whole UTC days, a month per transaction, and queues the days whose figures move."""
    raised = changed = dropped = 0
    chunks = month_chunks(first, last)
    for i, (a, b) in enumerate(chunks, start=1):
        async with engine.begin() as conn:
            res = await detect.run(conn, system, day_start(a), day_start(b) + DAY, rule_ids=rule_ids)
            if res.days:
                await detect.mark_days(conn, system, res.days, datetime.now(UTC).date())
        raised, changed, dropped = raised + res.raised, changed + res.changed, dropped + res.dropped
        if ctx is not None:
            await ctx.progress(
                i / len(chunks), f"{a}..{b} new {res.raised}, extended {res.changed}, gone {res.dropped}"
            )
    return f"rules: {raised} new suspect(s), {changed} extended, {dropped} no longer hold"


async def run_detect(ctx: JobContext, engine: AsyncEngine, system: System, params: dict[str, Any]) -> str:
    days = _days(params)
    rule_ids = [int(params["rule_id"])] if params.get("rule_id") else None
    found = await detect_range(engine, system, days[0], days[-1], rule_ids=rule_ids, ctx=ctx)
    return f"checked {len(days)} day(s); {found}"


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
            # The rules may have just changed (mandatory fields, in-service periods): read them fresh.
            async with engine.connect() as conn:
                system = await load_system(conn, params["system"]) or ingestor.system
            message = await run_recompute(ctx, engine, system, params)
        elif job["type"] == "detect":
            async with engine.connect() as conn:
                system = await load_system(conn, params["system"]) or ingestor.system
            message = await run_detect(ctx, engine, system, params)
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
