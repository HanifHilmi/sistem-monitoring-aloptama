"""Operator command line (NFR-OPS-001). Until the Admin UI exists (R2), jobs are started here.

simola migrate
simola load-history [--system WIDN-CAT3]              # enqueue reprocess from coverage start to today
simola reprocess --from 2026-10-01 --to 2026-10-31 [--inline]
simola recompute --from 2026-01-01 --to 2026-10-31
simola jobs | simola cancel <id>
simola import-legacy-probes --csv v2_probes.csv       # one-off at cutover (FR-ING-014)
simola dev-reset                                       # development only
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text

from simola.core.config import get_settings
from simola.core.db import make_engine
from simola.core.logging import setup_logging
from simola.core.timeutil import floor_minute
from simola.ingestion.cat3 import Cat3Ingestor
from simola.migrations.runner import ensure_app_role, migrate
from simola.registry import load_system
from simola.worker import jobs

DEFAULT_SYSTEM = "WIDN-CAT3"


async def _cmd_migrate(_a: argparse.Namespace) -> int:
    settings = get_settings()
    applied = await migrate(settings.asyncpg_dsn)
    role = None
    if settings.app_db_user and settings.app_db_password:
        await ensure_app_role(settings.asyncpg_dsn, settings.app_db_user, settings.app_db_password)
        role = settings.app_db_user
    print(json.dumps({"applied": applied, "app_role": role}))
    return 0


async def _with_system(code: str) -> tuple[Any, Any]:
    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=2, application_name="simola-cli")
    async with engine.connect() as conn:
        system = await load_system(conn, code)
    if system is None:
        await engine.dispose()
        raise SystemExit(f"unknown system {code!r}")
    return engine, system


async def _cmd_enqueue(job_type: str, params: dict[str, Any]) -> int:
    engine, _system = await _with_system(params["system"])
    try:
        job_id = await jobs.enqueue(engine, job_type, params)
        print(json.dumps({"job_id": job_id, "type": job_type, "params": params}))
    finally:
        await engine.dispose()
    return 0


async def _cmd_reprocess(a: argparse.Namespace) -> int:
    params = {"system": a.system, "from": a.from_, "to": a.to}
    if not a.inline:
        return await _cmd_enqueue("reprocess", params)
    engine, system = await _with_system(a.system)
    try:
        ing = Cat3Ingestor(engine, system, get_settings())
        job_id = await jobs.enqueue(engine, "reprocess", params, created_by="cli-inline")
        job = await jobs.claim(engine)
        assert job is not None and job["id"] == job_id, "another job was queued first; run without --inline"

        async def _ing(_code: str) -> Cat3Ingestor:
            return ing

        await jobs.execute(engine, job, _ing)
        await _print_job(engine, job_id)
    finally:
        await engine.dispose()
    return 0


async def _print_job(engine: Any, job_id: int) -> None:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text("SELECT id, type, status, message FROM job WHERE id = :i"), {"i": job_id}
                )
            )
            .mappings()
            .one()
        )
    print(json.dumps(dict(row), default=str))


async def _cmd_load_history(a: argparse.Namespace) -> int:
    engine, system = await _with_system(a.system)
    await engine.dispose()
    params = {
        "system": a.system,
        "from": system.coverage_start.date().isoformat(),
        "to": datetime.now(UTC).date().isoformat(),
    }
    return await _cmd_enqueue("reprocess", params)


async def _cmd_recompute(a: argparse.Namespace) -> int:
    return await _cmd_enqueue("recompute", {"system": a.system, "from": a.from_, "to": a.to})


async def _cmd_jobs(_a: argparse.Namespace) -> int:
    engine = make_engine(get_settings().database_url, pool_size=1)
    try:
        async with engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, type, status, round(progress::numeric, 3) AS progress, message, created_at, "
                            "finished_at FROM job ORDER BY id DESC LIMIT 20"
                        )
                    )
                )
                .mappings()
                .all()
            )
        for r in rows:
            print(json.dumps(dict(r), default=str))
    finally:
        await engine.dispose()
    return 0


async def _cmd_cancel(a: argparse.Namespace) -> int:
    engine = make_engine(get_settings().database_url, pool_size=1)
    try:
        async with engine.begin() as conn:
            n = (
                await conn.execute(
                    text(
                        "UPDATE job SET status = 'cancelled', finished_at = now() "
                        "WHERE id = :i AND status IN ('queued', 'running')"
                    ),
                    {"i": a.job_id},
                )
            ).rowcount
        print(json.dumps({"cancelled": bool(n)}))
    finally:
        await engine.dispose()
    return 0


async def _cmd_import_legacy(a: argparse.Namespace) -> int:
    """Import v2 live probe samples as legacy reachability (FR-ING-014).

    CSV columns: time (ISO-8601 UTC), cdp (CDP1/CDP2), reachable (t/f), rtt_ms. Export it read-only from v2
    with the runbook query, which excludes v2's minute-aligned backfill rows. SIMOLA's own probes win.
    """
    engine, system = await _with_system(a.system)
    agg: dict[tuple[int, datetime], list[Any]] = defaultdict(lambda: [0, 0, None])
    skipped = 0

    def _read_rows() -> list[dict[str, str]]:
        with open(a.csv, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    for row in await asyncio.to_thread(_read_rows):
        t = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise SystemExit("CSV times must carry a UTC offset")
        if t == floor_minute(t):
            skipped += 1  # minute-aligned rows are v2 backfill (file presence), not probes
            continue
        cdp = system.cdp_by_code(row["cdp"])
        if cdp is None:
            skipped += 1
            continue
        cell = agg[(cdp.id, floor_minute(t))]
        cell[0] += 1
        ok = row["reachable"].strip().lower() in ("t", "true", "1")
        cell[1] += int(ok)
        if ok and row.get("rtt_ms"):
            rtt = float(row["rtt_ms"])
            cell[2] = rtt if cell[2] is None else min(cell[2], rtt)
    params = [{"time": k[1], "cdp_id": k[0], "a": v[0], "o": v[1], "r": v[2]} for k, v in agg.items()]
    days = sorted({k[1].date() for k in agg})
    try:
        async with engine.begin() as conn:
            if params:
                await conn.execute(
                    text("""
                    INSERT INTO cdp_minute_fact (time, cdp_id, probes_attempted, probes_ok, rtt_min_ms, probe_method)
                    VALUES (:time, :cdp_id, :a, :o, :r, 'legacy-v2')
                    ON CONFLICT (cdp_id, time) DO UPDATE
                       SET probes_attempted = EXCLUDED.probes_attempted, probes_ok = EXCLUDED.probes_ok,
                           rtt_min_ms = EXCLUDED.rtt_min_ms, probe_method = 'legacy-v2'
                     WHERE cdp_minute_fact.probes_attempted = 0 OR cdp_minute_fact.probe_method = 'legacy-v2'
                """),
                    params,
                )
            if days:
                await conn.execute(
                    text(
                        "INSERT INTO rollup_dirty (system_id, day) SELECT :s, d FROM unnest(CAST(:days AS date[])) d "
                        "ON CONFLICT (system_id, day) DO UPDATE SET marked_at = now()"
                    ),
                    {"s": system.id, "days": days},
                )
    finally:
        await engine.dispose()
    print(json.dumps({"minutes": len(params), "skipped_rows": skipped, "days": len(days)}))
    return 0


async def _cmd_dev_reset(_a: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.environment != "development":
        print("refusing: dev-reset only runs with SIMOLA_ENVIRONMENT=development", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_url, pool_size=1)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()
    return await _cmd_migrate(_a)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="simola", description="SIMOLA operator commands")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    for name in ("reprocess", "recompute"):
        sp = sub.add_parser(name, help=f"enqueue a {name} job for a UTC date range")
        sp.add_argument("--system", default=DEFAULT_SYSTEM)
        sp.add_argument(
            "--from", dest="from_", required=True, type=lambda s: date.fromisoformat(s).isoformat()
        )
        sp.add_argument("--to", required=True, type=lambda s: date.fromisoformat(s).isoformat())
        if name == "reprocess":
            sp.add_argument("--inline", action="store_true", help="run in this process instead of the worker")
    lh = sub.add_parser("load-history", help="enqueue reprocess from coverage start to today")
    lh.add_argument("--system", default=DEFAULT_SYSTEM)
    sub.add_parser("jobs", help="list recent jobs")
    c = sub.add_parser("cancel", help="cancel a queued or running job")
    c.add_argument("job_id", type=int)
    il = sub.add_parser("import-legacy-probes", help="import v2 probe samples (CSV) as legacy reachability")
    il.add_argument("--system", default=DEFAULT_SYSTEM)
    il.add_argument("--csv", required=True)
    sub.add_parser("dev-reset", help="drop and recreate the schema (development only)")
    return p


COMMANDS = {
    "migrate": _cmd_migrate,
    "reprocess": _cmd_reprocess,
    "recompute": _cmd_recompute,
    "load-history": _cmd_load_history,
    "jobs": _cmd_jobs,
    "cancel": _cmd_cancel,
    "import-legacy-probes": _cmd_import_legacy,
    "dev-reset": _cmd_dev_reset,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(get_settings().log_level)
    return asyncio.run(COMMANDS[args.cmd](args))


if __name__ == "__main__":
    raise SystemExit(main())
