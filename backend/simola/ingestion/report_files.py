"""Reads the AWOS report logs of every CDP (FR-ING-009), on the same share threads as the 1-minute reader.

- Every cycle: today's METAR, METREPORT and TAF logs, and yesterday's for the first hours of the day, re-read only
  when their size or time changed.
- The history is loaded by a reprocess job with the source "reports" that an Admin starts (FR-ING-010: a deploy or
  restart never starts one by itself). Stored lines are skipped, so a reprocess adds only what is missing.
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

from simola import reports
from simola.core.timeutil import day_start
from simola.registry import Cdp, System

if TYPE_CHECKING:
    from simola.ingestion.cat3 import Cat3Ingestor

logger = logging.getLogger(__name__)


class ReportFolderMissing(OSError):
    pass


def source_name(system: System, cdp: Cdp) -> str:
    return f"{system.code}:{cdp.code}:reports"


@dataclass
class FileRead:
    rows: list[reports.ReportRow]
    warnings: int
    sig: tuple[int, int]


class ReportReader:
    def __init__(self, ingestor: Cat3Ingestor) -> None:
        self.ing = ingestor
        self._sig: dict[tuple[str, str], tuple[int, int]] = {}  # (CDP, file name) -> (size, mtime)
        self._lock = asyncio.Lock()

    @property
    def system(self) -> System:
        return self.ing.system  # follows registry reloads

    def folder(self, cdp_code: str) -> Path:
        return self.ing.paths[cdp_code] / "reports"

    # ------------------------------------------------------------------ files
    def _exists(self, cdp_code: str, name: str) -> bool:
        folder = self.folder(cdp_code)
        if (folder / name).exists():
            return True
        if not folder.is_dir():
            raise ReportFolderMissing(f"{cdp_code}: reports folder not readable")
        return False

    async def _read(self, cdp_code: str, type_: reports.ReportType, name: str, now: datetime) -> FileRead:
        path = self.folder(cdp_code) / name

        def _do() -> tuple[str, tuple[int, int]]:
            st = path.stat()
            return path.read_text(encoding="utf-8", errors="replace"), (st.st_size, st.st_mtime_ns)

        content, sig = await self.ing.on_share(cdp_code, _do)
        parsed = await asyncio.to_thread(
            reports.parse_text,
            content,
            type_,
            not_before=self.system.coverage_start,
            not_after=now + timedelta(seconds=self.ing.settings.future_tolerance_s),
        )
        return FileRead(parsed.rows, parsed.warnings, sig)

    async def _stat(self, cdp_code: str, name: str) -> tuple[int, int]:
        st = await self.ing.on_share(cdp_code, (self.folder(cdp_code) / name).stat)
        return (st.st_size, st.st_mtime_ns)

    async def _store(self, cdp: Cdp, rows: list[reports.ReportRow]) -> int:
        if not rows:
            return 0
        async with self._lock, self.ing.engine.begin() as conn:
            return await reports.store(conn, self.system, cdp, rows)

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
        """One pass over every CDP's report logs. Returns new lines per CDP (-1 when the folder failed)."""
        now = now or datetime.now(UTC)
        results = await asyncio.gather(
            *(self._cycle_cdp(c, now) for c in self.system.cdps), return_exceptions=True
        )
        out: dict[str, int] = {}
        for cdp, res in zip(self.system.cdps, results, strict=True):
            if isinstance(res, BaseException):
                logger.error("report cycle failed", extra={"cdp": cdp.code, "error": repr(res)})
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
                raise ReportFolderMissing(f"{cdp.code}: no share path configured")
            for day in self.ing.days_to_scan(now):
                for type_ in reports.TYPES:
                    name = reports.file_name_for(type_, day)
                    if not await self.ing.on_share(cdp.code, partial(self._exists, cdp.code, name)):
                        continue  # e.g. just after midnight, before the AWOS starts the day's log
                    sig = await self._stat(cdp.code, name)
                    if self._sig.get((cdp.code, name)) == sig:
                        continue
                    read = await self._read(cdp.code, type_, name, now)
                    new += await self._store(cdp, read.rows)
                    warnings += read.warnings
                    self._sig[(cdp.code, name)] = read.sig  # only after the lines are safely stored
                    if read.rows:
                        newest = max(r.logged_at for r in read.rows)
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
            logger.info("report lines stored", extra={"cdp": cdp.code, "rows": new})
        return new

    # ------------------------------------------------------------------ reprocess (FR-ING-010)
    async def reprocess_day(self, day: date, now: datetime | None = None) -> dict[str, Any]:
        """Re-reads one UTC day's report logs from every CDP. Stored lines are kept; missing ones are added."""
        now = now or datetime.now(UTC)
        out: dict[str, Any] = {"day": day.isoformat(), "cdps": {}}
        if day_start(day) + timedelta(days=1) <= self.system.coverage_start:
            return out
        for cdp in self.system.cdps:
            if cdp.code not in self.ing.paths:
                raise ReportFolderMissing(f"{cdp.code}: no share path configured")
            files = rows = added = warnings = 0
            for type_ in reports.TYPES:
                name = reports.file_name_for(type_, day)
                if not await self.ing.on_share(cdp.code, partial(self._exists, cdp.code, name)):
                    continue
                read = await self._read(cdp.code, type_, name, now)
                added += await self._store(cdp, read.rows)
                self._sig[(cdp.code, name)] = read.sig
                files += 1
                rows += len(read.rows)
                warnings += read.warnings
            out["cdps"][cdp.code] = {"files": files, "rows": rows, "new": added, "warnings": warnings}
        return out
