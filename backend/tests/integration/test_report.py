"""The monthly PDF report against a real database (R3.5, FR-EXP-001/003).

U6, the part a test can check: every figure the report prints is the dashboard's figure for the month. The report
is built from the answers of /kpis, /matrix, /outages, /data-quality and the alarm history; this test asks the API
for them and compares, with 3 November 2026 loaded (the pipeline tests' day). It also checks who may download the
report, that each one is audited, the shared limit of ten files a minute, and that only one is drawn at a time.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola import records
from simola.api.routers.exports import REPORT_LOCK
from simola.core.config import get_settings
from simola.ingestion.cat3 import Cat3Ingestor
from simola.registry import load_system
from simola.report.gather import gather
from simola.report.model import context
from simola.report.texts import Words
from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

SYS = "/api/v1/systems/WIDN-CAT3"
REPORT = f"{SYS}/exports/monthly-report"
NOVEMBER = "from=2026-11-01T00:00:00Z&to=2026-12-01T00:00:00Z"
LOADED = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)


def _json(x: Any) -> Any:
    """As the API would send it."""
    return json.loads(json.dumps(jsonable_encoder(x)))


@pytest.fixture(scope="module")
async def loaded(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        system = await load_system(conn, "WIDN-CAT3")
    assert system is not None
    ingestor = Cat3Ingestor(engine, system, get_settings())
    await ingestor.reprocess_day(date(2026, 11, 3), now=LOADED)
    await ingestor.alarms.reprocess_day(date(2026, 11, 3), now=LOADED)
    await _add_user(engine, "rp-admin", "admin")
    for name in ("rp-figures", "rp-viewer", "rp-busy"):
        await _add_user(engine, name, "viewer")
    yield
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))


async def test_every_figure_in_the_report_is_the_dashboards(engine: AsyncEngine, loaded: None) -> None:
    """U6: the report's month equals /kpis, /matrix, /outages, /data-quality and the alarm history."""
    async with Browser() as viewer:
        assert (await viewer.login("rp-figures")).status_code == 200
        for _ in range(3):  # all answers counted up to the same minute (the month may still be running)
            kpis = (await viewer.get(f"{SYS}/kpis?{NOVEMBER}")).json()
            matrix = (await viewer.get(f"{SYS}/matrix?{NOVEMBER}&bucket=day")).json()
            ola = (await viewer.get(f"{SYS}/outages?{NOVEMBER}&scope=ola&limit=15")).json()
            sla = (await viewer.get(f"{SYS}/outages?{NOVEMBER}&scope=sla&limit=1")).json()
            dq = (await viewer.get(f"{SYS}/data-quality?{NOVEMBER}")).json()
            ends = {a["period"]["evaluated_to"] for a in (kpis, matrix, ola, sla, dq)}
            if len(ends) == 1:
                break
        assert len(ends) == 1
        history = (await viewer.get(f"{SYS}/alarms?{NOVEMBER}&limit=1")).json()
        system_view = (await viewer.get(SYS)).json()
        definitions = (await viewer.get("/api/v1/definitions")).json()

    now = datetime.fromisoformat(kpis["period"]["as_of"])
    async with engine.connect() as conn:
        system = await load_system(conn, "WIDN-CAT3")
        assert system is not None
        r = await gather(conn, system, date(2026, 11, 1), "id", "Petugas", now)

    assert _json(r.kpis) == kpis
    assert kpis["sla"]["expected"] > 0  # 3 November is in it
    assert _json(r.system) == system_view
    assert _json(r.definitions) == definitions
    got = _json(r.matrix)
    assert (got["buckets"], got["rows"]) == (matrix["buckets"], matrix["rows"])
    for mine, theirs in ((_json(r.outages), ola), (_json(r.sla_outages), sla)):
        for key in ("availability", "by_cause", "intervals_total", "intervals"):
            assert mine[key] == theirs[key], key
    mine_dq = _json(r.quality)
    assert {k: v for k, v in mine_dq.items() if k != "period"} == {
        k: v for k, v in dq.items() if k != "period"
    }
    # alarms: the history's count of changes and its raised-per-day chart
    assert r.alarms["changes"] == history["total"]
    assert r.alarms["per_day"] == history["per_day"]
    raised = sum(d["error"] + d["warning"] for d in history["per_day"])
    assert sum(n["raised"] for n in r.alarms["names"]) == raised == sum(r.alarms["raised"].values())

    # and printed as the dashboard prints them (id: 99,84 and 44.640)
    ctx = context(r)
    w = Words("id")
    assert ctx["kpi_rows"][0]["pct"] == w.pct(kpis["sla"]["pct"])
    assert ctx["kpi_rows"][0]["expected"] == w.integer(kpis["sla"]["expected"])
    assert ctx["kpi_rows"][1]["pct"] == w.pct(kpis["ola"]["pct"])
    assert [g["pct"] for g in ctx["site_groups"]] == [w.pct(s["availability"]["pct"]) for s in kpis["sites"]]
    assert [x["total"] for x in ctx["days"]["matrix"]["rows"]] == [
        w.pct(x["total"]["pct"]) for x in matrix["rows"]
    ]
    assert len(ctx["outages"]["rows"]) == min(15, ola["intervals_total"])


async def test_calibration_is_shown_as_it_stood_at_the_end_of_the_month(
    engine: AsyncEngine, loaded: None
) -> None:
    """A record dated after the day is left out; a certificate validated after it was still pending then."""
    async with Browser() as admin:
        assert (await admin.login("rp-admin")).status_code == 200
        comps = {
            f"{c['site']}:{c['type']}": c["id"] for c in (await admin.get("/api/v1/admin/components")).json()
        }
        body = {
            "component_id": comps["middle:SOLR"],
            "date": "2020-01-10",
            "performed_by": "Calibration lab",
            "certificate": "CAL/R35",
            "next_due": "2021-01-10",
            "interval_months": None,
            "validated_on": "2020-02-01",
            "notes": "report test",
        }
        r = await admin.send("POST", "/api/v1/admin/calibrations", body)
        assert r.status_code == 201, r.text
        cal_id = r.json()["id"]
        try:
            async with engine.connect() as conn:
                system = await load_system(conn, "WIDN-CAT3")
                assert system is not None
                before = await records.calibration_on(conn, system, date(2020, 1, 5))
                january = await records.calibration_on(conn, system, date(2020, 1, 31))
                february = await records.calibration_on(conn, system, date(2020, 2, 29))

            def solr(x: dict[str, Any]) -> dict[str, Any]:
                return next(
                    c["calibration"] for c in x["components"] if (c["site"], c["type"]) == ("middle", "SOLR")
                )

            assert solr(before)["status"] == "unknown"
            assert solr(january) == {
                "status": "ok",
                "last": date(2020, 1, 10),
                "next_due": date(2021, 1, 10),
                "days_left": (date(2021, 1, 10) - date(2020, 1, 31)).days,
                "validated_on": None,
                "pending": True,
            }
            assert solr(february)["validated_on"] == date(2020, 2, 1)
            assert january["as_of"] == date(2020, 1, 31) and january["due_soon_days"] >= 0
        finally:
            await admin.send("DELETE", f"/api/v1/admin/calibrations/{cal_id}")


async def test_the_report_is_for_viewers_audited_and_drawn_one_at_a_time(
    engine: AsyncEngine, loaded: None
) -> None:
    async with Browser() as public:
        r = await public.send("POST", REPORT, {"month": "2026-11", "lang": "id"})
        assert r.status_code == 401
    async with Browser() as viewer:
        assert (await viewer.login("rp-viewer")).status_code == 200
        r = await viewer.send("POST", REPORT, {"month": "2026-11", "lang": "id"}, csrf=False)
        assert (r.status_code, r.json()["code"]) == (403, "csrf_failed")
        assert (await viewer.send("POST", REPORT, {"month": "2026-13", "lang": "id"})).status_code == 422
        assert (await viewer.send("POST", REPORT, {"month": "2026-11", "lang": "fr"})).status_code == 422
        future = (await viewer.send("POST", REPORT, {"month": "2999-01", "lang": "en"})).json()
        assert future["code"] == "month_in_future"

        r = await viewer.send("POST", REPORT, {"month": "2026-11", "lang": "en"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.headers["content-disposition"] == 'attachment; filename="SIMOLA_WIDN-CAT3_2026-11_en.pdf"'
        assert r.headers["cache-control"] == "no-store"
        assert r.content.startswith(b"%PDF-") and len(r.content) > 20_000

        # another report is being drawn (the lock held here): refused, nothing audited
        async with engine.connect() as held:
            assert await held.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": REPORT_LOCK})
            busy = await viewer.send("POST", REPORT, {"month": "2026-11", "lang": "id"})
            await held.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": REPORT_LOCK})
        assert (busy.status_code, busy.json()["code"]) == (429, "report_busy")

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT entity_id, after FROM audit_event WHERE action = 'export' AND actor = 'rp-viewer'"
                    )
                )
            )
            .mappings()
            .all()
        )
    assert [(a["entity_id"], a["after"]) for a in rows] == [
        ("monthly-report", {"system": "WIDN-CAT3", "month": "2026-11", "lang": "en"})
    ]


async def test_reports_and_csv_files_share_the_limit_of_ten_a_minute(loaded: None) -> None:
    async with Browser() as viewer:
        assert (await viewer.login("rp-busy")).status_code == 200
        for _ in range(9):
            q = "from=2026-11-03T00:00:00Z&to=2026-11-04T00:00:00Z"
            assert (await viewer.get(f"{SYS}/exports/quality.csv?{q}")).status_code == 200
        assert (await viewer.send("POST", REPORT, {"month": "2026-11", "lang": "id"})).status_code == 200
        r = await viewer.send("POST", REPORT, {"month": "2026-11", "lang": "id"})
        assert (r.status_code, r.json()["code"]) == (429, "too_many_exports")
