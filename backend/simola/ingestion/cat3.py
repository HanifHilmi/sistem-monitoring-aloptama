"""AWOS CAT.III file adapter (FR-ING-001/003/004/005/006/010/013).

Reads ``<share>/oneminute/091OneMinute.<YYYYMMDD>.dat`` from every CDP independently, stores the parsed
minutes per CDP, records data flow per CDP and minute, and rebuilds the merged minute table.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from simola.core.config import Settings
from simola.core.timeutil import DAY, MINUTE, day_start, floor_minute
from simola.ingestion import widn
from simola.ingestion.share import ShareIO
from simola.registry import Cdp, System

logger = logging.getLogger(__name__)

# Column order of awos_cat3_source_minute / awos_cat3_minute value columns (migration 0001).
CAT3_COLUMNS: tuple[str, ...] = (
    "temp_c",
    "dewp_c",
    "rh_pct",
    "qnh_hpa",
    "da_ft",
    "wind_speed_kt",
    "wind_dir_deg",
    "gust_speed_kt",
    "gust_dir_deg",
    "rvr_m",
    "vis_m",
    "als_cd",
    "als_dn",
    "rls",
    "lr1_100ft",
    "sky_condition",
    "precip_mm",
    "present_weather",
    "solar_wm2",
    "lightning",
)
_COLS = ", ".join(CAT3_COLUMNS)
_EXCL = ", ".join(f"EXCLUDED.{c}" for c in CAT3_COLUMNS)

UPSERT_SOURCE = text(f"""
    INSERT INTO awos_cat3_source_minute (time, cdp_id, site_id, all_missing, {_COLS})
    VALUES (:time, :cdp_id, :site_id, :all_missing, {", ".join(":" + c for c in CAT3_COLUMNS)})
    ON CONFLICT (cdp_id, site_id, time) DO UPDATE
       SET all_missing = EXCLUDED.all_missing, {", ".join(f"{c} = EXCLUDED.{c}" for c in CAT3_COLUMNS)},
           ingested_at = now()
     WHERE (awos_cat3_source_minute.all_missing, {", ".join("awos_cat3_source_minute." + c for c in CAT3_COLUMNS)})
           IS DISTINCT FROM (EXCLUDED.all_missing, {_EXCL})
""")

MARK_FLOW = text("""
    INSERT INTO cdp_minute_fact (time, cdp_id, data_flow)
    SELECT t, :cdp_id, true FROM unnest(CAST(:times AS timestamptz[])) AS t
    ON CONFLICT (cdp_id, time) DO UPDATE SET data_flow = true WHERE NOT cdp_minute_fact.data_flow
""")

# Merge (FR-ING-005): preferred CDP's record unless it is all-missing and another CDP has data.
MERGE_WINDOW = text(f"""
    INSERT INTO awos_cat3_minute (time, site_id, all_missing, {_COLS}, source_cdp_id, cdp_disagree)
    SELECT time, site_id, all_missing, {_COLS}, cdp_id, disagree
    FROM (
        SELECT s.*,
               min(md5(row({_COLS})::text)) OVER w <> max(md5(row({_COLS})::text)) OVER w AS disagree,
               row_number() OVER (PARTITION BY s.site_id, s.time ORDER BY s.all_missing, n.preference) AS rn
        FROM awos_cat3_source_minute s
        JOIN cdp_node n ON n.id = s.cdp_id
        WHERE n.system_id = :system_id AND s.time >= :start AND s.time < :end
        WINDOW w AS (PARTITION BY s.site_id, s.time)
    ) ranked
    WHERE rn = 1
    ON CONFLICT (site_id, time) DO UPDATE
       SET all_missing = EXCLUDED.all_missing, {", ".join(f"{c} = EXCLUDED.{c}" for c in CAT3_COLUMNS)},
           source_cdp_id = EXCLUDED.source_cdp_id, cdp_disagree = EXCLUDED.cdp_disagree
     WHERE (awos_cat3_minute.all_missing, {", ".join("awos_cat3_minute." + c for c in CAT3_COLUMNS)},
            awos_cat3_minute.source_cdp_id, awos_cat3_minute.cdp_disagree)
           IS DISTINCT FROM (EXCLUDED.all_missing, {_EXCL}, EXCLUDED.source_cdp_id, EXCLUDED.cdp_disagree)
""")

DELETE_ORPHAN_MERGED = text("""
    DELETE FROM awos_cat3_minute m
    USING site st
    WHERE st.id = m.site_id AND st.system_id = :system_id AND m.time >= :start AND m.time < :end
      AND NOT EXISTS (SELECT 1 FROM awos_cat3_source_minute s WHERE s.site_id = m.site_id AND s.time = m.time)
""")

MARK_DIRTY = text("""
    INSERT INTO rollup_dirty (system_id, day) SELECT :system_id, d FROM unnest(CAST(:days AS date[])) AS d
    ON CONFLICT (system_id, day) DO UPDATE SET marked_at = now()
""")


class SourceUnavailable(RuntimeError):
    """The CDP share (not just one file) cannot be read."""


@dataclass
class ParsedDay:
    cdp: Cdp
    day: date
    rows: list[dict[str, Any]]
    minutes: list[datetime]
    warnings: int
    duplicates: int
    sig: tuple[int, int]


def source_name(system: System, cdp: Cdp) -> str:
    return f"{system.code}:{cdp.code}:oneminute"


def rows_from_parse(
    system: System, cdp: Cdp, result: widn.ParseResult, *, day: date | None, not_after: datetime | None
) -> tuple[list[dict[str, Any]], list[datetime]]:
    """Convert parsed records to source rows; drop records outside ``day`` or after ``not_after``."""
    rows: list[dict[str, Any]] = []
    minutes: list[datetime] = []
    for rec in result.records:
        if day is not None and rec.time.date() != day:
            continue
        if not_after is not None and rec.time > not_after:
            continue  # clock skew / future records are ignored (PRD §8.6 E5)
        minutes.append(rec.time)
        for station, srec in rec.stations.items():
            site = system.site_by_station(station)
            if site is None:
                continue
            row: dict[str, Any] = dict.fromkeys(CAT3_COLUMNS)
            for code, value in srec.values.items():
                row[system.column(code)] = value
            row.update(time=rec.time, cdp_id=cdp.id, site_id=site.id, all_missing=srec.all_missing)
            rows.append(row)
    return rows, minutes


def _row_key(row: dict[str, Any]) -> tuple[int, int, datetime]:
    return (row["cdp_id"], row["site_id"], row["time"])


def _row_sig(row: dict[str, Any]) -> int:
    return hash((row["all_missing"], *(row[c] for c in CAT3_COLUMNS)))


class Cat3Ingestor:
    def __init__(self, engine: AsyncEngine, system: System, settings: Settings) -> None:
        self.engine = engine
        self.system = system
        self.settings = settings
        self.paths: dict[str, Path] = {
            c.code: Path(settings.cdp_paths[c.code]) for c in system.cdps if c.code in settings.cdp_paths
        }
        self._file_sig: dict[tuple[str, date], tuple[int, int]] = {}
        self._row_sig: dict[tuple[int, int, datetime], int] = {}
        self._write_lock = asyncio.Lock()
        self._oldest_checked: dict[str, datetime] = {}
        # Every call on a share runs on that CDP's own threads, so a dead share cannot stall the rest.
        self._share = {code: ShareIO(code, settings.file_io_timeout_s) for code in self.paths}

    # ------------------------------------------------------------------ files
    def resolve_file(self, cdp_code: str, day: date) -> Path | None:
        root = self.paths.get(cdp_code)
        if root is None:
            return None
        directory = root / "oneminute"
        exact = directory / widn.file_name_for(day.strftime("%Y%m%d"))
        if exact.exists():
            return exact
        if not directory.is_dir():
            raise SourceUnavailable(f"{cdp_code}: share directory not readable")
        matches = sorted(directory.glob(f"*OneMinute.{day.strftime('%Y%m%d')}.dat"))
        return matches[0] if matches else None

    async def _on_share[T](self, cdp_code: str, fn: Callable[[], T]) -> T:
        return await self._share[cdp_code].run(fn)

    async def _resolve(self, cdp_code: str, day: date) -> Path | None:
        return await self._on_share(cdp_code, partial(self.resolve_file, cdp_code, day))

    async def _read(self, cdp_code: str, path: Path) -> tuple[str, tuple[int, int]]:
        def _do() -> tuple[str, tuple[int, int]]:
            st = path.stat()
            return path.read_text(encoding="utf-8", errors="replace"), (st.st_size, st.st_mtime_ns)

        return await self._on_share(cdp_code, _do)

    async def _stat(self, cdp_code: str, path: Path) -> tuple[int, int]:
        st = await self._on_share(cdp_code, path.stat)
        return (st.st_size, st.st_mtime_ns)

    async def parse_day(self, cdp: Cdp, day: date, *, not_after: datetime | None) -> ParsedDay | None:
        path = await self._resolve(cdp.code, day)
        if path is None:
            return None
        content, sig = await self._read(cdp.code, path)
        result = await asyncio.to_thread(widn.parse_text, content)
        rows, minutes = rows_from_parse(self.system, cdp, result, day=day, not_after=not_after)
        return ParsedDay(cdp, day, rows, minutes, result.warnings, result.duplicate_minutes, sig)

    # ------------------------------------------------------------------ writes
    async def _write(
        self,
        conn: AsyncConnection,
        cdp: Cdp,
        rows: Sequence[dict[str, Any]],
        minutes: Iterable[datetime],
        today: date,
    ) -> None:
        if not rows:
            return
        await conn.execute(UPSERT_SOURCE, list(rows))
        flow_minutes = sorted(set(minutes))
        await conn.execute(MARK_FLOW, {"cdp_id": cdp.id, "times": flow_minutes})
        start = min(r["time"] for r in rows)
        end = max(r["time"] for r in rows) + MINUTE
        await conn.execute(MERGE_WINDOW, {"system_id": self.system.id, "start": start, "end": end})
        days = sorted({r["time"].date() for r in rows if r["time"].date() < today})
        if days:
            await conn.execute(MARK_DIRTY, {"system_id": self.system.id, "days": days})

    async def _status(self, conn: AsyncConnection, cdp: Cdp, **fields: Any) -> None:
        cols = ", ".join(fields)
        vals = ", ".join(f":{k}" for k in fields)
        sets = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields)
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
    def days_to_scan(self, now: datetime) -> list[date]:
        today = now.date()
        days = [today]
        if now - day_start(today) < timedelta(hours=self.settings.rescan_previous_day_hours):
            days.insert(0, today - timedelta(days=1))
        return days

    async def cycle(self, now: datetime | None = None) -> dict[str, int]:
        """One live ingestion cycle for all CDPs. Returns rows written per CDP code."""
        now = now or datetime.now(UTC)
        results = await asyncio.gather(
            *(self._cycle_cdp(c, now) for c in self.system.cdps), return_exceptions=True
        )
        out: dict[str, int] = {}
        for cdp, res in zip(self.system.cdps, results, strict=True):
            if isinstance(res, BaseException):
                logger.error("ingestion cycle failed", extra={"cdp": cdp.code, "error": repr(res)})
                out[cdp.code] = -1
            else:
                out[cdp.code] = res
        self._prune(now)
        return out

    async def _cycle_cdp(self, cdp: Cdp, now: datetime) -> int:
        not_after = now + timedelta(seconds=self.settings.future_tolerance_s)
        written = 0
        warnings = 0
        last_record: datetime | None = None
        try:
            if cdp.code not in self.paths:
                raise SourceUnavailable(f"{cdp.code}: no share path configured")
            for day in self.days_to_scan(now):
                path = await self._resolve(cdp.code, day)
                if path is None:
                    continue  # e.g. just after midnight before the CDP creates the new file (PRD §8.6 E4)
                sig = await self._stat(cdp.code, path)
                if self._file_sig.get((cdp.code, day)) == sig:
                    continue
                parsed = await self.parse_day(cdp, day, not_after=not_after)
                if parsed is None:
                    continue
                warnings += parsed.warnings
                changed = [r for r in parsed.rows if self._row_sig.get(_row_key(r)) != _row_sig(r)]
                if changed:
                    changed_minutes = {r["time"] for r in changed}
                    async with self._write_lock, self.engine.begin() as conn:
                        await self._write(conn, cdp, changed, changed_minutes, now.date())
                    for r in changed:
                        self._row_sig[_row_key(r)] = _row_sig(r)
                    written += len(changed)
                # Remember the file only after its rows are safely written, so failures are retried.
                self._file_sig[(cdp.code, day)] = parsed.sig
                if parsed.minutes:
                    last_record = (
                        max(parsed.minutes) if last_record is None else max(last_record, *parsed.minutes)
                    )
            oldest = await self._oldest_file(cdp, now)
            async with self.engine.begin() as conn:
                fields: dict[str, Any] = {
                    "available": True,
                    "last_attempt_at": now,
                    "last_success_at": now,
                    "last_error": None,
                }
                if last_record is not None:
                    fields["last_record_time"] = last_record
                if oldest is not None:
                    fields["oldest_file_date"] = oldest
                await self._status(conn, cdp, **fields)
                if warnings:
                    await conn.execute(
                        text(
                            "UPDATE ingest_status SET parse_warnings = parse_warnings + :w WHERE source = :s"
                        ),
                        {"w": warnings, "s": source_name(self.system, cdp)},
                    )
        except (OSError, TimeoutError, SourceUnavailable) as exc:
            async with self.engine.begin() as conn:
                await self._status(conn, cdp, available=False, last_attempt_at=now, last_error=str(exc)[:500])
            raise
        return written

    async def _oldest_file(self, cdp: Cdp, now: datetime) -> date | None:
        """Oldest 1-minute file on the share, checked hourly (assumption AS-7)."""
        last = self._oldest_checked.get(cdp.code)
        if last is not None and now - last < timedelta(hours=1):
            return None
        self._oldest_checked[cdp.code] = now
        directory = self.paths[cdp.code] / "oneminute"

        def _scan() -> date | None:
            stamps = sorted(
                n[-12:-4] for n in os.listdir(directory) if n.endswith(".dat") and "OneMinute" in n
            )
            for s in stamps:
                try:
                    return datetime.strptime(s, "%Y%m%d").date()
                except ValueError:
                    continue
            return None

        return await self._on_share(cdp.code, _scan)

    def _prune(self, now: datetime) -> None:
        cutoff = floor_minute(now) - timedelta(days=3)
        self._row_sig = {k: v for k, v in self._row_sig.items() if k[2] >= cutoff}
        keep_days = {now.date(), now.date() - timedelta(days=1)}
        self._file_sig = {k: v for k, v in self._file_sig.items() if k[1] in keep_days}

    # ------------------------------------------------------------------ reprocess (FR-ING-010)
    async def reprocess_day(self, day: date, now: datetime | None = None) -> dict[str, Any]:
        """Re-ingest one UTC day from all CDP files. Idempotent.

        Rows absent from an existing file are removed; a missing file is skipped without deleting
        anything (a file may be temporarily unreadable).
        """
        now = now or datetime.now(UTC)
        start, end = day_start(day), day_start(day) + DAY
        summary: dict[str, Any] = {"day": day.isoformat(), "cdps": {}}
        parsed_days: list[ParsedDay] = []
        for cdp in self.system.cdps:
            if cdp.code not in self.paths:
                raise SourceUnavailable(f"{cdp.code}: no share path configured")
            parsed = await self.parse_day(
                cdp, day, not_after=now + timedelta(seconds=self.settings.future_tolerance_s)
            )
            if parsed is None:
                summary["cdps"][cdp.code] = {"file": False}
                continue
            parsed_days.append(parsed)
            summary["cdps"][cdp.code] = {
                "file": True,
                "minutes": len(set(parsed.minutes)),
                "warnings": parsed.warnings,
                "duplicates": parsed.duplicates,
            }
        async with self._write_lock, self.engine.begin() as conn:
            for parsed in parsed_days:
                present = sorted(set(parsed.minutes))
                await conn.execute(
                    text("""
                    DELETE FROM awos_cat3_source_minute
                    WHERE cdp_id = :cdp AND time >= :start AND time < :end
                      AND NOT (time = ANY(CAST(:present AS timestamptz[])))
                """),
                    {"cdp": parsed.cdp.id, "start": start, "end": end, "present": present},
                )
                await conn.execute(
                    text("""
                    UPDATE cdp_minute_fact SET data_flow = false
                    WHERE cdp_id = :cdp AND time >= :start AND time < :end AND data_flow
                      AND NOT (time = ANY(CAST(:present AS timestamptz[])))
                """),
                    {"cdp": parsed.cdp.id, "start": start, "end": end, "present": present},
                )
                if parsed.rows:
                    await conn.execute(UPSERT_SOURCE, parsed.rows)
                    await conn.execute(MARK_FLOW, {"cdp_id": parsed.cdp.id, "times": present})
                for r in parsed.rows:
                    self._row_sig[_row_key(r)] = _row_sig(r)
            await conn.execute(MERGE_WINDOW, {"system_id": self.system.id, "start": start, "end": end})
            await conn.execute(
                DELETE_ORPHAN_MERGED, {"system_id": self.system.id, "start": start, "end": end}
            )
            if day < now.date():
                await conn.execute(MARK_DIRTY, {"system_id": self.system.id, "days": [day]})
        return summary
