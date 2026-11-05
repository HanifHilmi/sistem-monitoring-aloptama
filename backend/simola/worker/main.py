"""Worker process: ingestion, probes, rollups, jobs, heartbeat (PRD §11.9).

Only the leader (holder of a PostgreSQL advisory lock) works, so two workers overlapping during a deploy
cannot double-ingest. Run with: python -m simola.worker.main
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.core.config import Settings, get_settings
from simola.core.db import make_engine
from simola.core.logging import setup_logging
from simola.core.timeutil import day_start
from simola.dq import detect as dq_detect
from simola.dq import rules as dq_rules
from simola.ingestion.cat3 import Cat3Ingestor
from simola.ingestion.probe import Prober
from simola.kpi.engine import recompute_days
from simola.registry import System, get_setting, load_systems
from simola.worker import jobs

logger = logging.getLogger("simola.worker")
LEADER_KEY = 7_316_652_002
ALIVE_FILE = Path(os.environ.get("SIMOLA_WORKER_ALIVE_FILE", "/tmp/simola-worker.alive"))  # noqa: S108
WORKER_NAME = os.environ.get("HOSTNAME") or socket.gethostname()


async def _every(seconds: float, fn: Callable[[], Awaitable[None]], name: str) -> None:
    loop = asyncio.get_running_loop()
    while True:
        started = loop.time()
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("task iteration failed", extra={"task": name})
        await asyncio.sleep(max(1.0, seconds - (loop.time() - started)))


class Worker:
    def __init__(self, settings: Settings, engine: AsyncEngine) -> None:
        self.settings = settings
        self.engine = engine
        self.systems: list[System] = []
        self.ingestors: dict[str, Cat3Ingestor] = {}
        self.probers: dict[str, Prober] = {}
        self.leader = False
        self._finalised: set[tuple[date, int]] = set()
        self._registry_version: object = None

    async def load(self) -> None:
        async with self.engine.connect() as conn:
            self.systems = await load_systems(conn)
            self._registry_version = await get_setting(conn, "registry_version")
        for s in self.systems:
            if s.type_code == "AWOS_CAT3":
                self.ingestors[s.code] = Cat3Ingestor(self.engine, s, self.settings)
                self.probers[s.code] = Prober(
                    self.engine,
                    s.cdps,
                    self.settings.cdp_addresses,
                    self.settings.probe_ports,
                    self.settings.probe_timeout_s,
                )

    async def ingestor_for(self, code: str) -> Cat3Ingestor:
        if code not in self.ingestors:
            raise ValueError(f"no ingestor for system {code!r}")
        return self.ingestors[code]

    # -------------------------------------------------------------- tasks
    async def ingest(self) -> None:
        for code, ing in self.ingestors.items():
            written = await ing.cycle()
            logger.debug("ingest cycle", extra={"system": code, "rows": written})

    async def probe(self) -> None:
        for p in self.probers.values():
            await p.probe_once()
            await p.flush()

    async def refresh_registry(self) -> None:
        """Admins change mandatory fields and in-service periods (R2.2); they bump registry_version, and the
        worker then reloads the registry so its daily rollups follow the new rules."""
        async with self.engine.connect() as conn:
            version = await get_setting(conn, "registry_version")
            if version == self._registry_version:
                return
            systems = await load_systems(conn)
        self.systems = systems
        self._registry_version = version
        for s in systems:
            if s.code in self.ingestors:
                self.ingestors[s.code].system = s
        logger.info("registry reloaded", extra={"version": version})

    async def rollups(self) -> None:
        await self.refresh_registry()
        now = datetime.now(UTC)
        today = now.date()
        for s in self.systems:
            # Finalise yesterday once just after midnight and again after the re-scan window (FR-ING-006).
            for hour in (0, self.settings.rescan_previous_day_hours):
                if (
                    now >= day_start(today) + timedelta(hours=hour, minutes=10)
                    and (today, hour) not in self._finalised
                ):
                    async with self.engine.begin() as conn:
                        await conn.execute(
                            text(
                                "INSERT INTO rollup_dirty (system_id, day) VALUES (:s, :d) "
                                "ON CONFLICT (system_id, day) DO UPDATE SET marked_at = now()"
                            ),
                            {"s": s.id, "d": today - timedelta(days=1)},
                        )
                    self._finalised.add((today, hour))
            async with self.engine.begin() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT day, marked_at FROM rollup_dirty WHERE system_id = :s ORDER BY day LIMIT 31"
                        ),
                        {"s": s.id},
                    )
                ).all()
                if not rows:
                    continue
                await recompute_days(conn, s, [r[0] for r in rows], now)
                for d, marked in rows:
                    # Only clear marks we processed; a newer mark means data changed again meanwhile.
                    await conn.execute(
                        text(
                            "DELETE FROM rollup_dirty WHERE system_id = :s AND day = :d AND marked_at <= :m"
                        ),
                        {"s": s.id, "d": d, "m": marked},
                    )
        self._finalised = {k for k in self._finalised if k[0] >= today - timedelta(days=2)}

    async def detect_recent(self) -> None:
        """Runs the enabled rules over the latest minutes (FR-DQ-003, incremental): enough before them to see a
        stuck run or a spike whole, plus two hours for data that arrived late."""
        now = datetime.now(UTC)
        for s in self.systems:
            async with self.engine.begin() as conn:
                rules = await dq_detect.load_rules(conn, s)
                enabled = [r for r in rules if r.enabled]
                if not enabled:
                    continue
                lb = max(dq_rules.lookback(r.type, r.params) for r in enabled)
                b = now.replace(second=0, microsecond=0)
                res = await dq_detect.run(conn, s, b - timedelta(minutes=lb + 120), b, rules=rules)
                if res.days:
                    await dq_detect.mark_days(conn, s, res.days, now.date())
            if res.raised or res.changed or res.dropped:
                logger.info(
                    "rules checked",
                    extra={"system": s.code, "new": res.raised, "extended": res.changed, "gone": res.dropped},
                )

    async def run_jobs(self) -> None:
        job = await jobs.claim(self.engine)
        if job is not None:
            await jobs.execute(self.engine, job, self.ingestor_for)

    async def heartbeat(self) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("""
                INSERT INTO worker_heartbeat (worker, version, leader, last_beat) VALUES (:w, :v, :l, now())
                ON CONFLICT (worker) DO UPDATE SET version = EXCLUDED.version, leader = EXCLUDED.leader,
                       last_beat = now()
            """),
                {"w": WORKER_NAME, "v": self.settings.version, "l": self.leader},
            )
            await conn.execute(
                text("DELETE FROM worker_heartbeat WHERE last_beat < now() - interval '1 day'")
            )
        await asyncio.to_thread(ALIVE_FILE.touch)  # container healthcheck reads its age (DOC-05)

    # -------------------------------------------------------------- leadership
    async def run(self) -> None:
        await self.load()
        beat = asyncio.create_task(_every(30, self.heartbeat, "heartbeat"))
        try:
            while True:
                lock_conn = await asyncpg.connect(
                    self.settings.asyncpg_dsn, server_settings={"application_name": "simola-worker-lock"}
                )
                try:
                    if not await lock_conn.fetchval("SELECT pg_try_advisory_lock($1)", LEADER_KEY):
                        self.leader = False
                        await asyncio.sleep(10)
                        continue
                    self.leader = True
                    logger.info("worker is leader", extra={"worker": WORKER_NAME})
                    interrupted = await jobs.mark_interrupted(self.engine)
                    if interrupted:
                        logger.warning("marked running jobs as interrupted", extra={"count": interrupted})
                    tasks = [
                        asyncio.create_task(_every(self.settings.ingest_interval_s, self.ingest, "ingest")),
                        asyncio.create_task(_every(self.settings.probe_interval_s, self.probe, "probe")),
                        asyncio.create_task(_every(30, self.rollups, "rollups")),
                        asyncio.create_task(_every(5, self.run_jobs, "jobs")),
                        asyncio.create_task(_every(60, self.detect_recent, "detect")),
                    ]
                    try:
                        while not lock_conn.is_closed():
                            await asyncio.sleep(15)
                            await lock_conn.fetchval("SELECT 1")  # raises if the lock connection died
                    finally:
                        for t in tasks:
                            t.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        self.leader = False
                except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
                    logger.exception("lost leadership connection; retrying")
                finally:
                    with contextlib.suppress(Exception):
                        await lock_conn.close()
                await asyncio.sleep(5)
        finally:
            beat.cancel()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    engine = make_engine(settings.database_url, pool_size=5, application_name="simola-worker")
    try:
        await Worker(settings, engine).run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
