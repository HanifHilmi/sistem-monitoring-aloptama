"""METAR, MET REPORT and TAF against a real database, with both CDPs' logs of 1 November 2026 (R3.2).

FR-ING-009 acceptance: every METAR line of a reference day's file appears exactly once. The reports are public.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola import reports
from simola.core.config import get_settings
from simola.ingestion.cat3 import Cat3Ingestor
from simola.ingestion.report_files import ReportReader
from simola.registry import System, load_system
from simola.worker import jobs
from tests.conftest import fixture_text
from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

SYS = "/api/v1/systems/WIDN-CAT3"
DAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)


async def _system(engine: AsyncEngine) -> System:
    async with engine.connect() as conn:
        system = await load_system(conn, "WIDN-CAT3")
    assert system is not None
    return system


def _reader(system: System, engine: AsyncEngine) -> ReportReader:
    return Cat3Ingestor(engine, system, get_settings()).reports


def _expected(type_: reports.ReportType, prefix: str) -> list[reports.MergedReport]:
    """The reports both CDPs' files hold, merged here without the database."""
    by_text: dict[str, list[tuple]] = defaultdict(list)  # type: ignore[type-arg]
    for cdp_id, cdp in ((1, "cdp1"), (2, "cdp2")):
        for r in reports.parse_text(fixture_text(f"{cdp}_{prefix}.20261101.log"), type_).rows:
            by_text[r.text].append((r.logged_at, cdp_id, r.kind, r.notes, r.runway, r.bulletin))
    return [m for rows in by_text.values() for m in reports.merge_copies(rows, {1: 1, 2: 2})]


async def test_both_cdps_logs_are_stored_once_and_rereading_adds_nothing(engine: AsyncEngine) -> None:
    system = await _system(engine)
    reader = _reader(system, engine)
    first = await reader.reprocess_day(DAY, now=NOW)
    assert first["cdps"] == {
        "CDP1": {"files": 3, "rows": 115, "new": 115, "warnings": 0},  # 55 METAR/SPECI, 57 MET REPORT, 3 TAF
        "CDP2": {"files": 3, "rows": 115, "new": 115, "warnings": 0},
    }
    again = await reader.reprocess_day(DAY, now=NOW)
    assert all(v["new"] == 0 for v in again["cdps"].values())
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM report_source_row"))).scalar_one() == 230
        rows = (
            await conn.execute(text("SELECT type, cdp_ids FROM report_entry WHERE logged_at < '2026-11-02'"))
        ).all()
    for type_, prefix in (("metar", "METAR"), ("metreport", "METREPORT"), ("taf", "TAF")):
        mine = [r.cdp_ids for r in rows if r.type == type_]
        assert len(mine) == len(_expected(type_, prefix)), type_  # type: ignore[arg-type]
        # FR-ING-009 acceptance: each CDP's every line is in exactly one report
        for cdp_id, cdp in ((1, "cdp1"), (2, "cdp2")):
            lines = reports.parse_text(fixture_text(f"{cdp}_{prefix}.20261101.log"), type_).rows  # type: ignore[arg-type]
            assert sum(cdp_id in c for c in mine) == len(lines), (type_, cdp)


async def test_the_live_reader_reads_todays_and_yesterdays_logs(engine: AsyncEngine) -> None:
    system = await _system(engine)
    reader = _reader(system, engine)
    assert await reader.cycle(NOW) == {
        "CDP1": 0,
        "CDP2": 0,
    }  # 1 November is already stored; no 2 November logs
    async with engine.connect() as conn:
        status = (
            await conn.execute(
                text("SELECT source, available FROM ingest_status WHERE source LIKE :k"), {"k": "%:reports"}
            )
        ).all()
    assert sorted(status) == [("WIDN-CAT3:CDP1:reports", True), ("WIDN-CAT3:CDP2:reports", True)]


async def test_everyone_sees_the_latest_a_day_and_a_search() -> None:
    async with Browser() as visitor:
        latest = (await visitor.get(f"{SYS}/reports/latest")).json()
        assert [len(latest[t]) for t in ("metar", "metreport", "taf")] == [6, 6, 3]
        newest = latest["metar"][0]
        assert newest["logged_at"].startswith("2026-11-01T23:5") and newest["text"].endswith("=")
        assert newest["cdps"] == ["CDP1", "CDP2"] and newest["runway"] == "04"
        times = [r["logged_at"] for r in latest["metar"]]
        assert times == sorted(times, reverse=True)

        day = (await visitor.get(f"{SYS}/reports?day=2026-11-01&type=taf")).json()
        assert day["counts"]["taf"] == 3 and day["counts"]["metar"] == len(_expected("metar", "METAR"))
        assert [r["bulletin"] for r in day["reports"]] == [
            "FTID32 WIDN 010500",
            "FTID32 WIDN 011700",
            "FTID32 WIDN 012300",
        ]
        assert day["reports"][0]["text"].count("\n") == 1 and day["reports"][0]["cdps"] == ["CDP1", "CDP2"]

        q = "from=2026-11-01&to=2026-11-01"
        found = (await visitor.get(f"{SYS}/reports/search?{q}&type=metar&q=visibility%20decrease")).json()
        assert found["total"] >= 1 and all(r["kind"] == "SPECI" for r in found["reports"])
        assert any("visibility decrease" in n for r in found["reports"] for n in r["notes"])
        tsra = (await visitor.get(f"{SYS}/reports/search?{q}&type=taf&q=tsra")).json()
        assert tsra["total"] == 3
        assert (await visitor.get(f"{SYS}/reports/search?{q}&type=taf&q=100%25")).json()["total"] == 0

        long = await visitor.get(f"{SYS}/reports/search?from=2026-09-01&to=2026-11-01&type=metar")
        assert long.status_code == 422 and long.json()["code"] == "period_too_long"
        backwards = await visitor.get(f"{SYS}/reports/search?from=2026-11-02&to=2026-11-01")
        assert backwards.status_code == 422 and backwards.json()["code"] == "invalid_period"
        future = await visitor.get(f"{SYS}/reports?day=2999-01-01&type=metar")
        assert future.status_code == 422 and future.json()["code"] == "future_day"


async def test_a_reprocess_can_read_the_report_logs_only(engine: AsyncEngine) -> None:
    await _add_user(engine, "rp-admin", "admin")
    system = await _system(engine)
    ingestor = Cat3Ingestor(engine, system, get_settings())
    async with engine.begin() as conn:  # only one reprocess may be queued: clear what earlier tests left
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))
    async with Browser() as admin:
        assert (await admin.login("rp-admin")).status_code == 200
        r = await admin.send(
            "POST",
            "/api/v1/admin/jobs",
            {"type": "reprocess", "from": "2026-11-01", "to": "2026-11-01", "sources": ["reports"]},
        )
        assert r.status_code == 201, r.text
        job = r.json()
        assert job["params"]["sources"] == ["reports"]
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE job SET status = 'running' WHERE id = :id"), {"id": job["id"]})

        async def ingestor_for(_code: str) -> Cat3Ingestor:
            return ingestor

        await jobs.execute(
            engine, {"id": job["id"], "type": "reprocess", "params": job["params"]}, ingestor_for
        )
        done = (await admin.get(f"/api/v1/admin/jobs/{job['id']}")).json()
        assert done["status"] == "done", done
        assert done["message"] == "reprocessed 1 day(s) of report files; 0 new report line(s)"
        assert "reports:CDP1=115" in done["log"]
    assert jobs.reprocess_sources({}) == ["minutes", "alarms", "reports"]
