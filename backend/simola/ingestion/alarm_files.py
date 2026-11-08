"""Reads the AWOS alarm files of every CDP (FR-ING-008), on the same share threads as the 1-minute reader.

- Every cycle: today's file, and yesterday's for the first hours of the day, re-read only when their size or time
  changed.
- The history, or a day missed while the worker was down, is read by a reprocess job with the source "alarms" that
  an Admin starts (FR-ING-010: a deploy or restart never starts one by itself). Stored rows are skipped.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from simola import alarms
from simola.core.timeutil import day_start
from simola.registry import Cdp, System

if TYPE_CHECKING:
    from simola.ingestion.cat3 import Cat3Ingestor

logger = logging.getLogger(__name__)


class AlarmFolderMissing(OSError):
    pass


def source_name(system: System, cdp: Cdp) -> str:
    return f"{system.code}:{cdp.code}:alarms"


@dataclass
class FileRead:
    rows: list[alarms.AlarmRow]
    warnings: int
    sig: tuple[int, int]


class AlarmReader:
    def __init__(self, ingestor: Cat3Ingestor) -> None:
        self.ing = ingestor
        self._sig: dict[tuple[str, str], tuple[int, int]] = {}  # (CDP, file name) -> (size, mtime)
        self._lock = asyncio.Lock()

    @property
    def system(self) -> System:
        return self.ing.system  # follows registry reloads

    def folder(self, cdp_code: str) -> Path:
        return self.ing.paths[cdp_code] / "alarm"

    # ------------------------------------------------------------------ files
    def _resolve(self, cdp_code: str, day: date) -> str | None:
        folder = self.folder(cdp_code)
        exact = folder / alarms.file_name_for(day)
        if exact.exists():
            return exact.name
        if not folder.is_dir():
            raise AlarmFolderMissing(f"{cdp_code}: alarm folder not readable")
        matches = sorted(folder.glob(f"*ALARM.{day.strftime('%Y%m%d')}.dat"))
        return matches[0].name if matches else None

    async def _read(self, cdp_code: str, name: str, now: datetime) -> FileRead:
        path = self.folder(cdp_code) / name

        def _do() -> tuple[str, tuple[int, int]]:
            st = path.stat()
            return path.read_text(encoding="utf-8", errors="replace"), (st.st_size, st.st_mtime_ns)

        content, sig = await self.ing.on_share(cdp_code, _do)
        parsed = await asyncio.to_thread(
            alarms.parse_text,
            content,
            not_before=self.system.coverage_start,
            not_after=now + timedelta(seconds=self.ing.settings.future_tolerance_s),
        )
        return FileRead(parsed.rows, parsed.warnings, sig)

    async def _stat(self, cdp_code: str, name: str) -> tuple[int, int]:
        st = await self.ing.on_share(cdp_code, (self.folder(cdp_code) / name).stat)
        return (st.st_size, st.st_mtime_ns)

    async def _files_to_check(self, cdp: Cdp, now: datetime) -> list[str]:
        names = []
        for day in self.ing.days_to_scan(now):
            n = await self.ing.on_share(cdp.code, partial(self._resolve, cdp.code, day))
            if n is not None:
                names.append(n)
        return names

    # ------------------------------------------------------------------ writes
    async def _store(self, cdp: Cdp, rows: list[alarms.AlarmRow]) -> int:
        if not rows:
            return 0
        async with self._lock, self.ing.engine.begin() as conn:
            return await alarms.store(conn, self.system, cdp, rows)

    async def _status(self, cdp: Cdp, **fields: Any) -> None:
        cols = ", ".join(fields)
        vals = ", ".join(f":{k}" for k in fields)
        sets = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields)
        async with self.ing.engine.begin() as conn:
            await conn.execute(
                text(f"""
                INSERT INTO ingest_status (source, system_id, cdp_id, {cols}, updated_at)
                VALUES (:source, :system_id, :cdp_id, {vals}, now())
                ON CONFLICT (source) DO UPDATE SET {sets}, updated_at = now()
            """),
                {
                    "source": source_name(self.system, cdp),
                    "system_id": self.system.id,
                    "cdp_id": cdp.id,
                    **fields,
                },
            )

    # ------------------------------------------------------------------ live cycle
    async def cycle(self, now: datetime | None = None) -> dict[str, int]:
        """One pass over every CDP's alarm folder. Returns new rows per CDP (-1 when the folder failed)."""
        now = now or datetime.now(UTC)
        results = await asyncio.gather(
            *(self._cycle_cdp(c, now) for c in self.system.cdps), return_exceptions=True
        )
        out: dict[str, int] = {}
        for cdp, res in zip(self.system.cdps, results, strict=True):
            if isinstance(res, BaseException):
                logger.error("alarm cycle failed", extra={"cdp": cdp.code, "error": repr(res)})
                out[cdp.code] = -1
            else:
                out[cdp.code] = res
        keep = {d.strftime("%Y%m%d") for d in (now.date(), now.date() - timedelta(days=1))}
        self._sig = {k: v for k, v in self._sig.items() if k[1].split(".")[1] in keep}
        return out

    async def _cycle_cdp(self, cdp: Cdp, now: datetime) -> int:
        new = warnings = 0
        last_row: datetime | None = None
        try:
            if cdp.code not in self.ing.paths:
                raise AlarmFolderMissing(f"{cdp.code}: no share path configured")
            for name in await self._files_to_check(cdp, now):
                sig = await self._stat(cdp.code, name)
                if self._sig.get((cdp.code, name)) == sig:
                    continue
                read = await self._read(cdp.code, name, now)
                new += await self._store(cdp, read.rows)
                warnings += read.warnings
                self._sig[(cdp.code, name)] = read.sig  # only after the rows are safely stored
                if read.rows:
                    newest = max(r.time for r in read.rows)
                    last_row = newest if last_row is None else max(last_row, newest)
            fields: dict[str, Any] = {
                "available": True,
                "last_attempt_at": now,
                "last_success_at": now,
                "last_error": None,
            }
            if last_row is not None:
                fields["last_record_time"] = last_row
            await self._status(cdp, **fields)
            if warnings:
                async with self.ing.engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE ingest_status SET parse_warnings = parse_warnings + :w WHERE source = :s"
                        ),
                        {"w": warnings, "s": source_name(self.system, cdp)},
                    )
        except (OSError, TimeoutError) as exc:
            await self._status(cdp, available=False, last_attempt_at=now, last_error=str(exc)[:500])
            raise
        if new:
            logger.info("alarm rows stored", extra={"cdp": cdp.code, "rows": new})
        return new

    # ------------------------------------------------------------------ reprocess (FR-ING-010)
    async def reprocess_day(self, day: date, now: datetime | None = None) -> dict[str, Any]:
        """Re-reads one UTC day's alarm file from every CDP. Stored rows are kept; rows missing are added."""
        now = now or datetime.now(UTC)
        out: dict[str, Any] = {"day": day.isoformat(), "cdps": {}}
        if day_start(day) + timedelta(days=1) <= self.system.coverage_start:
            return out
        for cdp in self.system.cdps:
            if cdp.code not in self.ing.paths:
                raise AlarmFolderMissing(f"{cdp.code}: no share path configured")
            name = await self.ing.on_share(cdp.code, partial(self._resolve, cdp.code, day))
            if name is None:
                out["cdps"][cdp.code] = {"file": False}
                continue
            read = await self._read(cdp.code, name, now)
            added = await self._store(cdp, read.rows)
            self._sig[(cdp.code, name)] = read.sig
            out["cdps"][cdp.code] = {
                "file": True,
                "rows": len(read.rows),
                "new": added,
                "warnings": read.warnings,
            }
        return out
