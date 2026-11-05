"""End-to-end pipeline on real CDP files: ingestion -> merge -> data flow -> KPIs -> API (PRD §15.2)."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.api.app import create_app
from simola.api.deps import clear_registry_cache
from simola.core.config import get_settings
from simola.ingestion import widn
from simola.ingestion.cat3 import Cat3Ingestor
from simola.kpi import engine as kpi
from simola.migrations.runner import MigrationError, migrate
from simola.registry import load_system
from simola.worker import jobs
from tests.conftest import fixture_text, missing_minutes
from tests.integration.conftest import LEAK_PROBE_ADDRESS

pytestmark = pytest.mark.integration

DAY = date(2026, 11, 3)
DAY_START = datetime(2026, 11, 3, tzinfo=UTC)
DAY_END = datetime(2026, 11, 4, tzinfo=UTC)
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)


async def _system(engine: AsyncEngine):  # type: ignore[no-untyped-def]
    async with engine.connect() as conn:
        system = await load_system(conn, "WIDN-CAT3")
    assert system is not None
    return system


@pytest.fixture(scope="module")
async def loaded(engine: AsyncEngine):  # type: ignore[no-untyped-def]
    system = await _system(engine)
    ing = Cat3Ingestor(engine, system, get_settings())
    summary = await ing.reprocess_day(DAY, now=NOW)
    return system, ing, summary


async def test_migrations_are_idempotent_and_immutable(engine: AsyncEngine, tmp_path: Path) -> None:
    dsn = get_settings().asyncpg_dsn
    assert await migrate(dsn) == []
    from simola.migrations.runner import SQL_DIR

    for f in SQL_DIR.glob("*.sql"):
        (tmp_path / f.name).write_text(
            f.read_text() + ("\n-- tampered\n" if f.name.startswith("0001") else "")
        )
    with pytest.raises(MigrationError, match="checksum mismatch"):
        await migrate(dsn, tmp_path)


async def test_reprocess_counts_match_source_files(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    system, _ing, summary = loaded
    assert summary["cdps"]["CDP1"]["minutes"] == 1430
    assert summary["cdps"]["CDP2"]["minutes"] == 1433
    async with engine.connect() as conn:
        flow = dict(
            (
                await conn.execute(
                    text(
                        "SELECT n.code, count(*) FROM cdp_minute_fact f JOIN cdp_node n ON n.id = f.cdp_id "
                        "WHERE f.data_flow AND f.time >= :a AND f.time < :b GROUP BY n.code"
                    ),
                    {"a": DAY_START, "b": DAY_END},
                )
            ).all()
        )
        site04 = system.site_by_slug("04")
        merged = {
            r[0]
            for r in (
                await conn.execute(
                    text("SELECT time FROM awos_cat3_minute WHERE site_id = :s AND time >= :a AND time < :b"),
                    {"s": site04.id, "a": DAY_START, "b": DAY_END},
                )
            ).all()
        }
    assert flow == {"CDP1": 1430, "CDP2": 1433}
    assert missing_minutes(merged, "2026-11-03") == ["00:30", "10:50", "10:51", "10:52"]  # FR-ING-005 AC1


def _python_recount(system, comp_type: str, slug: str) -> int:  # type: ignore[no-untyped-def]
    """Independent recount: merge per minute in Python (CDP1 preferred unless all-missing)."""
    site = system.site_by_slug(slug)
    comp = next(c for c in site.components if c.type_code == comp_type)
    p1 = {
        r.time: r.stations[site.station_code]
        for r in widn.parse_text(fixture_text("cdp1_091OneMinute.20261103.dat")).records
    }
    p2 = {
        r.time: r.stations[site.station_code]
        for r in widn.parse_text(fixture_text("cdp2_091OneMinute.20261103.dat")).records
    }
    valid = 0
    for t in set(p1) | set(p2):
        rec = p1.get(t)
        if rec is None or (rec.all_missing and t in p2 and not p2[t].all_missing):
            rec = p2[t]
        if comp.is_dcp:
            ok = any(rec.values.get(f) is not None for c in site.sensor_components for f in c.fields)
        else:
            ok = all(rec.values.get(f) is not None for f in comp.mandatory)
        valid += int(ok)
    return valid


async def test_kpis_match_independent_recount(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    system, *_ = loaded
    async with engine.connect() as conn:
        counts = await kpi.live_counts(conn, system, DAY_START, DAY_END)
    assert counts.get(("sla", system.id)) == (1436, 1440)
    cdp1, cdp2 = system.cdps
    assert counts.get(("cdp_flow", cdp1.id)) == (1430, 1440)
    assert counts.get(("cdp_flow", cdp2.id)) == (1433, 1440)
    for site in system.sites:
        for comp in site.components:
            expected_valid = _python_recount(system, comp.type_code, site.slug)
            assert counts.get(("component", comp.id)) == (expected_valid, 1440), (site.slug, comp.type_code)


async def test_reprocess_is_idempotent(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    system, ing, _ = loaded
    async with engine.connect() as conn:
        before = (await kpi.live_counts(conn, system, DAY_START, DAY_END)).data
        rows_before = (await conn.execute(text("SELECT count(*) FROM awos_cat3_source_minute"))).scalar_one()
    await ing.reprocess_day(DAY, now=NOW)
    async with engine.connect() as conn:
        after = (await kpi.live_counts(conn, system, DAY_START, DAY_END)).data
        rows_after = (await conn.execute(text("SELECT count(*) FROM awos_cat3_source_minute"))).scalar_one()
    assert dict(before) == dict(after)
    assert rows_before == rows_after


async def test_rollup_equals_live(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    system, *_ = loaded
    async with engine.begin() as conn:
        assert await kpi.recompute_days(conn, system, [DAY], NOW) == 1
    async with engine.connect() as conn:
        live = await kpi.live_counts(conn, system, DAY_START, DAY_END)
        via_rollup, a, b = await kpi.period_counts(conn, system, DAY_START, DAY_END, NOW)
        n_rollup = (
            await conn.execute(text("SELECT count(*) FROM availability_daily WHERE day = :d"), {"d": DAY})
        ).scalar_one()
    assert (a, b) == (DAY_START, DAY_END)
    assert n_rollup > 0
    assert dict(live.data) == dict(via_rollup.data)


async def test_grouped_counts_equal_summed_days(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    """The database's per-group sums give exactly the per-day counts added up (matrix and KPIs, FR-KPI-001)."""
    system, *_ = loaded
    async with engine.begin() as conn:
        assert await kpi.recompute_days(conn, system, [DAY], NOW) == 1
    start = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)  # partial first day, stored full day, partial last day
    nonzero = lambda c: {k: tuple(v) for k, v in c.data.items() if v != [0, 0]}  # noqa: E731
    async with engine.connect() as conn:
        days, a, b = await kpi.daily_counts(conn, system, start, NOW, NOW)
        for group in ("day", "week", "month", "all"):
            expected: dict[date, kpi.Counts] = {}
            for d, c in days.items():
                expected.setdefault(kpi.group_key(d, group, start.date()), kpi.Counts()).merge(c)
            got, ga, gb = await kpi.grouped_counts(conn, system, start, NOW, NOW, group)
            assert (ga, gb) == (a, b)
            assert {k: nonzero(c) for k, c in got.items()} == {k: nonzero(c) for k, c in expected.items()}, (
                group
            )


async def test_live_cycle_after_midnight_rescans_yesterday(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    system, *_ = loaded
    fresh = Cat3Ingestor(engine, system, get_settings())
    now = datetime(2026, 11, 4, 0, 30, tzinfo=UTC)  # today's file does not exist (PRD §8.6 E4)
    assert fresh.days_to_scan(now) == [date(2026, 11, 3), date(2026, 11, 4)]
    result = await fresh.cycle(now)
    assert set(result) == {"CDP1", "CDP2"} and all(v >= 0 for v in result.values())
    async with engine.connect() as conn:
        live = await kpi.live_counts(conn, system, DAY_START, DAY_END)
        status = (await conn.execute(text("SELECT count(*) FROM ingest_status WHERE available"))).scalar_one()
    assert live.get(("sla", system.id)) == (1436, 1440)
    assert status == 2


async def test_reprocess_job_runs_end_to_end(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    """A queued job is claimed, runs, logs progress and finishes (FR-ING-010, FR-ADM-002)."""
    _system, ing, _ = loaded
    job_id = await jobs.enqueue(
        engine, "reprocess", {"system": "WIDN-CAT3", "from": "2026-11-03", "to": "2026-11-03"}
    )
    job = await jobs.claim(engine)
    assert job is not None and job["id"] == job_id

    async def _ing(_code: str) -> Cat3Ingestor:
        return ing

    await jobs.execute(engine, job, _ing)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, progress, log, message FROM job WHERE id = :i"), {"i": job_id}
            )
        ).one()
    assert row.status == "done", row.message
    assert row.progress == 1.0
    assert "2026-11-03 CDP1=1430 CDP2=1433" in row.log


async def test_one_active_reprocess_job(engine: AsyncEngine) -> None:
    first = await jobs.enqueue(
        engine, "reprocess", {"system": "WIDN-CAT3", "from": "2026-11-03", "to": "2026-11-03"}
    )
    with pytest.raises(IntegrityError):
        await jobs.enqueue(
            engine, "reprocess", {"system": "WIDN-CAT3", "from": "2026-11-03", "to": "2026-11-03"}
        )
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE id = :i"), {"i": first})


_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


async def test_api_figures_and_public_shaping(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    clear_registry_cache()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    q = "from=2026-11-03T00:00:00Z&to=2026-11-04T00:00:00Z"
    public_paths = [
        "/api/v1/systems",
        "/api/v1/systems/WIDN-CAT3",
        f"/api/v1/systems/WIDN-CAT3/kpis?{q}",
        "/api/v1/systems/WIDN-CAT3/status",
        "/api/v1/systems/WIDN-CAT3/problems",
        "/api/v1/systems/WIDN-CAT3/history?from=2026-11-01T00:00:00Z&to=2026-11-04T00:00:00Z&bucket=day",
        "/api/v1/systems/WIDN-CAT3/calendar?year=2026&metric=cdp:CDP1",
        f"/api/v1/systems/WIDN-CAT3/sites/04/components/ANEM/series?{q}",
        f"/api/v1/systems/WIDN-CAT3/sites/22/components/CEL/series?{q}",
        "/api/v1/settings/display",
    ]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        bodies = {}
        for path in public_paths:
            r = await client.get(path)
            assert r.status_code == 200, (path, r.text[:300])
            bodies[path] = r.text
            assert LEAK_PROBE_ADDRESS not in r.text and not _IPV4.search(r.text), path  # FR-AUTH-006
            assert "/cdp1" not in r.text and "/cdp2" not in r.text, path
        k = json.loads(bodies[f"/api/v1/systems/WIDN-CAT3/kpis?{q}"])
        assert k["sla"] == {"valid": 1436, "expected": 1440, "missing": 4, "pct": 99.72}
        assert [c["uptime"]["valid"] for c in k["cdps"]] == [1430, 1433]
        assert k["cdps"][0]["reachability"]["pct"] is None  # no probes in this test -> "not measured"
        internal = await client.get("/api/v1/internal/health")
        assert internal.status_code == 200 and LEAK_PROBE_ADDRESS in internal.text
        bad = await client.get(
            "/api/v1/systems/WIDN-CAT3/kpis?from=2026-11-04T00:00:00Z&to=2026-11-03T00:00:00Z"
        )
        assert bad.status_code == 422 and bad.headers["content-type"].startswith("application/problem+json")
        series = json.loads(bodies[f"/api/v1/systems/WIDN-CAT3/sites/04/components/ANEM/series?{q}"])
        assert {f["code"] for f in series["fields"]} == {"WS", "WD", "WGS", "WGD"} and "wind" in series
        ready = await client.get("/ready")
        assert ready.status_code == 200


async def test_matrix_and_minutes_match_kpis(engine: AsyncEngine, loaded) -> None:  # type: ignore[no-untyped-def]
    """Board matrix and minute view agree with the KPI engine for the same day (FR-KPI-001, FR-DSH-009)."""
    clear_registry_cache()
    transport = httpx.ASGITransport(app=create_app())
    q = "from=2026-11-03T00:00:00Z&to=2026-11-04T00:00:00Z"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        k = (await client.get(f"/api/v1/systems/WIDN-CAT3/kpis?{q}")).json()
        m = (await client.get(f"/api/v1/systems/WIDN-CAT3/matrix?{q}&bucket=day")).json()
        rows = {r["key"]: r for r in m["rows"]}
        assert rows["sla"]["total"] == k["sla"]
        assert rows["sla"]["cells"][0]["valid"] == 1436
        atrh = next(
            c for s in k["sites"] if s["slug"] == "04" for c in s["components"] if c["type"] == "ATRH"
        )
        assert rows["component:04:ATRH"]["total"] == atrh["availability"]

        mins = (
            await client.get("/api/v1/systems/WIDN-CAT3/minutes?day=2026-11-03&scope=component:04:ATRH")
        ).json()
        assert len(mins["codes"]) == 1440
        assert mins["valid"] == atrh["availability"]["valid"]
        assert sum(r["minutes"] for r in mins["intervals"]) == mins["expected"] - mins["valid"]

        cdp1 = (await client.get("/api/v1/systems/WIDN-CAT3/minutes?day=2026-11-03&scope=cdp:CDP1")).json()
        assert cdp1["codes"].count("n") == 10  # CDP1's file lacks exactly 10 minutes that day

        bad = await client.get("/api/v1/systems/WIDN-CAT3/minutes?day=2026-11-03&scope=component:04:NOPE")
        assert bad.status_code == 404

        series = (await client.get(f"/api/v1/systems/WIDN-CAT3/sites/04/components/ATRH/series?{q}")).json()
        temp = next(f for f in series["fields"] if f["code"] == "TEMP")
        assert (
            temp["stats"]["count"] > 1400
            and temp["stats"]["min"] <= temp["stats"]["mean"] <= temp["stats"]["max"]
        )
