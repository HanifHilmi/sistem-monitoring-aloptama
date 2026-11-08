"""CSV exports against a real database (R3.4, FR-EXP-002/003).

U7 acceptance: summing the daily file gives the period's figures, exactly as the dashboard shows them. The minute
file says for every minute what the minute map says; the alarm file lists what the alarm history lists; the flag
file lists the flag put on 3 November 2026 (the day the pipeline tests load), which is removed again at the end.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola import exports
from simola.core.config import get_settings
from simola.ingestion.cat3 import Cat3Ingestor
from simola.registry import load_system
from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

SYS = "/api/v1/systems/WIDN-CAT3"
EXP = f"{SYS}/exports"
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
PERIOD = "from=2026-11-01T00:00:00Z&to=2026-11-04T00:00:00Z"
DAY = "from=2026-11-03T00:00:00Z&to=2026-11-04T00:00:00Z"


def _rows(r: httpx.Response) -> list[dict[str, str]]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["cache-control"] == "no-store"
    body = r.content.decode("utf-8")
    assert body.startswith(exports.BOM)
    return list(csv.DictReader(io.StringIO(body.removeprefix(exports.BOM))))


def _header(r: httpx.Response) -> list[str]:
    return next(csv.reader(io.StringIO(r.content.decode("utf-8").removeprefix(exports.BOM))))


@pytest.fixture(scope="module")
async def flagged(engine: AsyncEngine) -> AsyncIterator[int]:
    """3 November loaded (minutes and alarms), with a maintenance flag on Runway 04's barometer, 06:00–07:00."""
    async with engine.connect() as conn:
        system = await load_system(conn, "WIDN-CAT3")
    assert system is not None
    ingestor = Cat3Ingestor(engine, system, get_settings())
    await ingestor.reprocess_day(date(2026, 11, 3), now=NOW)
    await ingestor.alarms.reprocess_day(date(2026, 11, 3), now=NOW)  # adds nothing when already read
    await _add_user(engine, "ex-admin", "admin")
    for name in ("ex-daily", "ex-minutes", "ex-alarms", "ex-quality", "ex-busy"):
        await _add_user(engine, name, "viewer")
    async with Browser() as admin:
        assert (await admin.login("ex-admin")).status_code == 200
        comps = {
            f"{c['site']}:{c['type']}": c["id"] for c in (await admin.get("/api/v1/admin/components")).json()
        }
        r = await admin.send(
            "POST",
            "/api/v1/admin/flags",
            {
                "component_ids": [comps["04:BARO"]],
                "start": "2026-11-03T06:00:00Z",
                "end": "2026-11-03T07:00:00Z",
                "reason": "maintenance",
                "note": "export test",
            },
        )
        assert r.status_code == 201, r.text
        flag_id = int(r.json()["flag"]["id"] if "flag" in r.json() else r.json()["id"])
    yield flag_id
    async with Browser() as admin:
        assert (await admin.login("ex-admin")).status_code == 200
        await admin.send("DELETE", f"/api/v1/admin/flags/{flag_id}")
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))


def _pct(v: int, e: int) -> float | None:
    if e == 0:
        return None
    return float((Decimal(v) * 100 / Decimal(e)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


async def test_the_daily_file_adds_up_to_the_figures(engine: AsyncEngine, flagged: int) -> None:
    """U7: re-importing the daily file and summing it gives the dashboard's figures for the period."""
    async with Browser() as viewer:
        assert (await viewer.login("ex-daily")).status_code == 200
        r = await viewer.get(f"{EXP}/daily.csv?{PERIOD}")
        rows = _rows(r)
        assert _header(r) == exports.DAILY_HEADER
        assert r.headers["content-disposition"] == (
            'attachment; filename="SIMOLA_WIDN-CAT3_daily_2026-11-01_2026-11-03.csv"'
        )
        kpis = (await viewer.get(f"{SYS}/kpis?{PERIOD}")).json()

    sums: dict[tuple[str, str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for row in rows:
        s = sums[(row["scope"], row["cdp"], row["site"], row["component"])]
        s[0] += int(row["valid_min"])
        s[1] += int(row["expected_min"])
        s[2] += int(row["reachable_min"] or 0)
        s[3] += int(row["probed_min"] or 0)
        assert int(row["missing_min"]) == int(row["expected_min"]) - int(row["valid_min"])
        assert row["definitions_version"] == "1.0"
    assert {r["date_utc"] for r in rows} <= {"2026-11-01", "2026-11-02", "2026-11-03"}

    v, e, *_ = sums[("system", "", "", "")]
    assert (v, e) == (kpis["sla"]["valid"], kpis["sla"]["expected"])
    for c in kpis["cdps"]:
        fv, fe, rv, pv = sums[("cdp", c["code"], "", "")]
        assert (fv, fe) == (c["uptime"]["valid"], c["uptime"]["expected"]), c["code"]
        assert (rv, pv) == (c["reachability"]["reachable"], c["reachability"]["sampled"]), c["code"]
    ratios = []
    pooled = [0, 0]
    for s in kpis["sites"]:
        sv, se, *_ = sums[("site", "", s["code"], "")]
        assert (sv, se) == (s["availability"]["valid"], s["availability"]["expected"]), s["code"]
        if se:
            ratios.append(Decimal(sv) / Decimal(se))
        for comp in s["components"]:
            cv, ce, *_ = sums[("component", "", s["code"], comp["type"])]
            assert (cv, ce) == (comp["availability"]["valid"], comp["availability"]["expected"])
            pooled[0] += cv
            pooled[1] += ce
    # OLA: the average of the sites' figures for the whole period, then rounded (PRD §7.3.1)
    ola = float(
        (sum(ratios, Decimal(0)) / len(ratios) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    assert ola == kpis["ola"]["pct"]
    assert _pct(*pooled) == kpis["pooled"]["pct"]

    async with engine.connect() as conn:
        a = (
            (
                await conn.execute(
                    text(
                        "SELECT entity_id, after FROM audit_event WHERE action = 'export' AND actor = 'ex-daily'"
                    )
                )
            )
            .mappings()
            .one()
        )
    assert a["entity_id"] == "daily"
    assert a["after"]["system"] == "WIDN-CAT3" and a["after"]["from"].startswith("2026-11-01")


async def test_the_minute_file_says_what_the_minute_map_says(flagged: int) -> None:
    async with Browser() as viewer:
        assert (await viewer.login("ex-minutes")).status_code == 200
        r = await viewer.get(f"{EXP}/minutes.csv?{DAY}&site=04")
        rows = _rows(r)
        header = _header(r)
        assert r.headers["content-disposition"].endswith('_minutes_RWY04_2026-11-03_2026-11-03.csv"')
        system = (await viewer.get(SYS)).json()
        site = next(s for s in system["sites"] if s["slug"] == "04")
        expected_header = ["time_utc", "cdps"]
        for c in site["components"]:
            expected_header.append(f"{c['type']}.status")
            for f in c["fields"]:
                unit = system["fields"][f]["unit"]
                expected_header.append(f"{c['type']}.{f} ({unit})" if unit else f"{c['type']}.{f}")
        assert header == [*expected_header, *exports.TRAILER]  # what the Exports page lists
        assert len(rows) == 1440
        assert (
            rows[0]["time_utc"] == "2026-11-03T00:00:00Z" and rows[-1]["time_utc"] == "2026-11-03T23:59:00Z"
        )
        for c in site["components"]:
            m = (await viewer.get(f"{SYS}/minutes?day=2026-11-03&scope=component:04:{c['type']}")).json()
            column = [row[f"{c['type']}.status"] for row in rows]
            assert column == [exports.MINUTE_STATUS[x] for x in m["codes"]], c["type"]
            assert column.count("valid") == m["valid"], c["type"]
    baro = [row["BARO.status"] for row in rows]
    assert "flagged" in baro[360:420] and "flagged" not in baro[:360] + baro[420:]
    # a minute with a record names the CDPs it came from
    assert all(row["cdps"] for row in rows if row["DCP.status"] != "no_data")
    assert all(not row["cdps"] for row in rows if row["DCP.status"] == "no_data")


async def test_the_alarm_file_lists_the_alarm_history(flagged: int) -> None:
    q = "from=2026-11-02T00:00:00Z&to=2026-11-04T00:00:00Z"
    async with Browser() as viewer:
        assert (await viewer.login("ex-alarms")).status_code == 200
        r = await viewer.get(f"{EXP}/alarms.csv?{q}")
        rows = _rows(r)
        assert _header(r) == exports.ALARM_HEADER
        history = (await viewer.get(f"{SYS}/alarms?{q}&order=asc&limit=200")).json()
        assert len(rows) == history["total"] > 0
        assert [(x["time_utc"], x["alarm_name"]) for x in rows] == [
            (e["time"].replace("+00:00", "Z"), e["name"]) for e in history["events"]
        ]
        assert {x["change"] for x in rows} <= {"raised", "acknowledged", "cleared"}
        errors = _rows(await viewer.get(f"{EXP}/alarms.csv?{q}&type=error"))
        assert errors and all(x["type"] == "error" for x in errors)
        assert len(errors) == (await viewer.get(f"{SYS}/alarms?{q}&type=error")).json()["total"]


async def test_the_quality_file_lists_flags_and_detections(flagged: int) -> None:
    async with Browser() as viewer:
        assert (await viewer.login("ex-quality")).status_code == 200
        rows = _rows(await viewer.get(f"{EXP}/quality.csv?{DAY}"))
        flag = next(x for x in rows if x["kind"] == "flag" and x["id"] == str(flagged))
        assert {k: flag[k] for k in ("site", "component", "start_utc", "end_utc", "minutes", "reason")} == {
            "site": "RWY04",
            "component": "BARO",
            "start_utc": "2026-11-03T06:00:00Z",
            "end_utc": "2026-11-03T07:00:00Z",
            "minutes": "60",
            "reason": "maintenance",
        }
        assert (flag["status"], flag["counts"], flag["note"], flag["by"]) == (
            "active",
            "true",
            "export test",
            "ex-admin",
        )
        assert all(x["status"] == "confirmed" for x in rows if x["kind"] == "detection")
        only = _rows(await viewer.get(f"{EXP}/quality.csv?{DAY}&records=detections&all=1"))
        assert all(x["kind"] == "detection" for x in only)
        assert len(only) >= sum(1 for x in rows if x["kind"] == "detection")


async def test_exports_are_for_viewers_within_limits(flagged: int) -> None:
    async with Browser() as public:
        r = await public.get(f"{EXP}/daily.csv?{DAY}")
        assert r.status_code == 401
    async with Browser() as viewer:
        assert (await viewer.login("ex-busy")).status_code == 200
        long = await viewer.get(
            f"{EXP}/minutes.csv?from=2026-10-01T00:00:00Z&to=2026-11-02T00:00:00Z&site=04"
        )
        assert (long.status_code, long.json()["code"]) == (422, "period_too_long")
        unknown = await viewer.get(f"{EXP}/minutes.csv?{DAY}&site=99")
        assert (unknown.status_code, unknown.json()["code"]) == (404, "site_not_found")
        for _ in range(10):  # API-10: ten files a minute (the refused ones above are not counted)
            assert (await viewer.get(f"{EXP}/quality.csv?{DAY}")).status_code == 200
        busy = await viewer.get(f"{EXP}/quality.csv?{DAY}")
        assert (busy.status_code, busy.json()["code"]) == (429, "too_many_exports")
