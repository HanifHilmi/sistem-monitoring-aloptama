"""Network reachability probes (FR-ING-007). Informational only: probes never feed SLA.

Method: TCP connect to the configured ports (default 445, the SMB service SIMOLA reads from). The first port
that accepts a connection counts as success. Results are aggregated per CDP per UTC minute.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.core.timeutil import floor_minute
from simola.registry import Cdp

logger = logging.getLogger(__name__)


async def tcp_probe(host: str, ports: list[int], timeout_s: float) -> tuple[bool, float | None, str | None]:
    last_error = "no ports configured"
    for port in ports:
        started = time.perf_counter()
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_s)
        except (TimeoutError, OSError) as exc:
            last_error = f"tcp/{port}: {type(exc).__name__}"
            continue
        rtt = (time.perf_counter() - started) * 1000.0
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True, round(rtt, 2), None
    return False, None, last_error


@dataclass
class MinuteAgg:
    attempted: int = 0
    ok: int = 0
    rtt_min: float | None = None
    last_error: str | None = None


FLUSH = text("""
    INSERT INTO cdp_minute_fact (time, cdp_id, probes_attempted, probes_ok, rtt_min_ms, probe_method, last_error)
    VALUES (:time, :cdp_id, :attempted, :ok, :rtt, :method, :err)
    ON CONFLICT (cdp_id, time) DO UPDATE
       SET probes_attempted = EXCLUDED.probes_attempted, probes_ok = EXCLUDED.probes_ok,
           rtt_min_ms = EXCLUDED.rtt_min_ms, probe_method = EXCLUDED.probe_method,
           last_error = EXCLUDED.last_error
""")


class Prober:
    def __init__(
        self,
        engine: AsyncEngine,
        cdps: tuple[Cdp, ...],
        addresses: dict[str, str],
        ports: list[int],
        timeout: float,
    ) -> None:
        self.engine = engine
        self.cdps = [c for c in cdps if c.code in addresses]
        self.addresses = addresses
        self.ports = ports
        self.timeout = timeout
        self.method = "tcp:" + ",".join(str(p) for p in ports)
        self._agg: dict[tuple[int, datetime], MinuteAgg] = {}

    async def probe_once(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        minute = floor_minute(now)
        results = await asyncio.gather(
            *(tcp_probe(self.addresses[c.code], self.ports, self.timeout) for c in self.cdps)
        )
        for cdp, (ok, rtt, err) in zip(self.cdps, results, strict=True):
            agg = self._agg.setdefault((cdp.id, minute), MinuteAgg())
            agg.attempted += 1
            if ok:
                agg.ok += 1
                agg.rtt_min = (
                    rtt if agg.rtt_min is None or (rtt is not None and rtt < agg.rtt_min) else agg.rtt_min
                )
            else:
                agg.last_error = err

    async def flush(self, now: datetime | None = None, *, include_current: bool = False) -> int:
        """Write completed minutes (and optionally the current one) to cdp_minute_fact."""
        now = now or datetime.now(UTC)
        current = floor_minute(now)
        ready = [(k, v) for k, v in self._agg.items() if include_current or k[1] < current]
        if not ready:
            return 0
        params = [
            {
                "time": k[1],
                "cdp_id": k[0],
                "attempted": v.attempted,
                "ok": v.ok,
                "rtt": v.rtt_min,
                "method": self.method,
                "err": v.last_error,
            }
            for k, v in ready
        ]
        async with self.engine.begin() as conn:
            await conn.execute(FLUSH, params)
        for k, _ in ready:
            self._agg.pop(k, None)
        return len(params)
