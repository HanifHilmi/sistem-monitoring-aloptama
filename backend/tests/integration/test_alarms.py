"""AWOS alarms against a real database, with the CDPs' real alarm files of 2–3 November 2026 (R3.1).

FR-ING-008 acceptance: re-reading a file adds nothing; on 2026-11-03 the "error" alarms list the three DCP*_Missing
alarms of 10:43, next to the 10:38–10:54 data gap. The public sees only the number of active alarms.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola import alarms
from simola.core.config import get_settings
from simola.ingestion.alarm_files import AlarmReader
from simola.ingestion.cat3 import Cat3Ingestor
from simola.registry import System, load_system
from simola.worker import jobs
from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

SYS = "/api/v1/systems/WIDN-CAT3"
NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)
DAY_Q = "from=2026-11-03T00:00:00Z&to=2026-11-04T00:00:00Z"


async def _system(engine: AsyncEngine) -> System:
    async with engine.connect() as conn:
        system = await load_system(conn, "WIDN-CAT3")
    assert system is not None
    return system


def _reader(system: System, engine: AsyncEngine) -> AlarmReader:
    return Cat3Ingestor(engine, system, get_settings()).alarms


async def _count(engine: AsyncEngine, sql: str) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(sql))).scalar_one())


@pytest.fixture(scope="module")
async def people(engine: AsyncEngine) -> AsyncIterator[None]:
    await _add_user(engine, "al-admin", "admin")
    await _add_user(engine, "al-viewer", "viewer")
    yield


async def test_both_cdps_files_are_stored_once_and_rereading_adds_nothing(engine: AsyncEngine) -> None:
    system = await _system(engine)
    reader = _reader(system, engine)
    first = await reader.reprocess_day(date(2026, 11, 3), now=NOW)
    assert first["cdps"] == {
        "CDP1": {"file": True, "rows": 7, "new": 7, "warnings": 0},
        "CDP2": {"file": True, "rows": 7, "new": 7, "warnings": 0},
    }
    again = await reader.reprocess_day(date(2026, 11, 3), now=NOW)
    assert all(v["new"] == 0 for v in again["cdps"].values())
    assert await _count(engine, "SELECT count(*) FROM alarm_source_row") == 14
    # Each CDP logged every change itself, up to a second apart: seven changes, each from both CDPs.
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT name, time, cdp_ids FROM alarm_event ORDER BY time"))).all()
    assert len(rows) == 7
    assert all(len(r.cdp_ids) == 2 for r in rows)
    assert rows[0].time == datetime(2026, 11, 3, 10, 43, 49, tzinfo=UTC)  # the earlier of the two CDPs


async def test_the_live_reader_loads_the_history_once(engine: AsyncEngine) -> None:
    system = await _system(engine)
    reader = _reader(system, engine)  # a fresh worker: it lists every alarm file on the shares
    new = await reader.cycle(NOW)
    assert new == {"CDP1": 7, "CDP2": 7}  # 2 November; 3 November is already stored
    assert await reader.cycle(NOW + timedelta(minutes=1)) == {"CDP1": 0, "CDP2": 0}
    # 2 November: CDP2 logged the DCP alarms 85 s after CDP1. Still one change each.
    async with engine.connect() as conn:
        nov2 = (
            await conn.execute(
                text(
                    "SELECT name, cdp_ids FROM alarm_event WHERE time < '2026-11-03' AND name LIKE 'DCP_\\_Missing'"
                )
            )
        ).all()
        status = (
            await conn.execute(
                text("SELECT source, available FROM ingest_status WHERE source LIKE '%:alarms'")
            )
        ).all()
    assert len(nov2) == 3 and all(len(r.cdp_ids) == 2 for r in nov2)
    assert sorted(status) == [("WIDN-CAT3:CDP1:alarms", True), ("WIDN-CAT3:CDP2:alarms", True)]


async def test_errors_of_3_november_show_the_dcp_alarms_at_the_data_gap(people: None) -> None:
    async with Browser() as viewer:
        assert (await viewer.login("al-viewer")).status_code == 200
        page = (await viewer.get(f"{SYS}/alarms?{DAY_Q}&type=error&order=asc")).json()
    at_gap = [e for e in page["events"] if "10:38" <= e["time"][11:16] <= "10:54"]
    assert [e["name"] for e in at_gap] == ["DCPA_Missing", "DCPB_Missing", "DCPC_Missing"]
    assert all(e["raised"] and e["cdps"] == ["CDP1", "CDP2"] for e in at_gap)
    assert [e["place"] for e in at_gap] == [
        {"kind": "component", "site": s, "component": "DCP"} for s in ("04", "middle", "22")
    ]
    assert page["total"] == 5
    assert page["per_day"] == [{"day": "2026-11-03", "error": 5, "warning": 0}]


async def test_history_filters(people: None) -> None:
    async with Browser() as viewer:
        assert (await viewer.login("al-viewer")).status_code == 200

        async def names(q: str) -> list[str]:
            r = await viewer.get(f"{SYS}/alarms?{DAY_Q}&{q}")
            assert r.status_code == 200, r.text
            return [e["name"] for e in r.json()["events"]]

        assert await names("scope=site:middle") == ["DCPB_Missing"]
        assert sorted(await names("scope=component:22:PWX")) == [
            "DCP6498CpsbDegradedError",
            "DCP6498CpsbDegradedWarning",
        ]
        assert await names("scope=station") == []
        assert await names("name=degraded%20performance%20warning&type=warning") == [
            "DCP6498ApsbDegradedWarning",
            "DCP6498CpsbDegradedWarning",
        ]
        assert await names("name=100%25") == []  # the search is literal text
        assert await names("active=false") == []  # no clear was logged that day
        page = (await viewer.get(f"{SYS}/alarms?{DAY_Q}&limit=2&offset=6")).json()
        assert page["total"] == 7 and len(page["events"]) == 1
        bad = await viewer.get(f"{SYS}/alarms?{DAY_Q}&scope=site:nowhere")
        assert bad.status_code == 404 and bad.json()["code"] == "scope_not_found"
        long = await viewer.get(f"{SYS}/alarms?from=2025-01-01T00:00:00Z&to=2026-11-04T00:00:00Z")
        assert long.status_code == 422 and long.json()["code"] == "period_too_long"


async def _store(engine: AsyncEngine, *rows: alarms.AlarmRow) -> None:
    system = await _system(engine)
    async with engine.begin() as conn:
        await alarms.store(conn, system, system.cdps[0], list(rows))


async def _forget(engine: AsyncEngine, name: str, since: datetime) -> None:
    system = await _system(engine)
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM alarm_source_row WHERE name = :n AND time >= :t"), {"n": name, "t": since}
        )
        await alarms.rebuild(conn, system, name)


async def test_active_alarms_and_the_problems_panel(engine: AsyncEngine, people: None) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    msg = "The GPS device cannot receive a satellite signal."
    async with Browser() as viewer, Browser() as visitor:
        assert (await viewer.login("al-viewer")).status_code == 200
        # The November rows say active but are days old: no clear was logged, so they are not active now.
        current = (await viewer.get(f"{SYS}/alarms/active")).json()
        assert current["window_hours"] == alarms.OPEN_HOURS
        assert current["active"] == []
        assert len(current["not_cleared"]) == 7
        assert not [
            p
            for p in (await visitor.get(f"{SYS}/problems")).json()["problems"]
            if p["code"] == "alarms_active"
        ]

        try:
            await _store(
                engine,
                alarms.AlarmRow(now - timedelta(hours=1), "GPSActiveError", "error", "pending", True, msg),
            )
            current = (await viewer.get(f"{SYS}/alarms/active")).json()
            assert [a["name"] for a in current["active"]] == ["GPSActiveError"]
            assert current["active"][0]["place"] == {"kind": "station", "site": None, "component": None}
            assert (await viewer.get(f"{SYS}/alarms/active?scope=site:04")).json()["active"] == []

            public = await visitor.get(f"{SYS}/problems")
            item = next(p for p in public.json()["problems"] if p["code"] == "alarms_active")
            assert item == {
                "code": "alarms_active",
                "severity": "minor",
                "link": "/systems/WIDN-CAT3",
                "params": {"n": 1, "errors": 1},
            }
            assert "GPS" not in public.text  # the count only: no names or messages for the public
            signed = (await viewer.get(f"{SYS}/problems")).json()["problems"]
            assert (
                next(p for p in signed if p["code"] == "alarms_active")["link"] == "/systems/WIDN-CAT3/alarms"
            )
            assert (await visitor.get(f"{SYS}/alarms/active")).status_code == 401

            # Cleared: no longer active, and gone from the Problems panel.
            await _store(
                engine,
                alarms.AlarmRow(now - timedelta(minutes=5), "GPSActiveError", "error", "pending", False, msg),
            )
            assert (await viewer.get(f"{SYS}/alarms/active")).json()["active"] == []
            assert not [
                p
                for p in (await visitor.get(f"{SYS}/problems")).json()["problems"]
                if p["code"] == "alarms_active"
            ]
        finally:
            await _forget(engine, "GPSActiveError", now - timedelta(days=1))


async def _audit(admin: Browser, action: str) -> list[dict[str, Any]]:
    return list((await admin.get(f"/api/v1/admin/audit?action={action}")).json()["events"])


async def test_an_admin_moves_an_alarm_for_its_whole_history(people: None) -> None:
    async with Browser() as admin, Browser() as viewer:
        assert (await admin.login("al-admin")).status_code == 200
        assert (await viewer.login("al-viewer")).status_code == 200
        listed = {n["name"]: n for n in (await admin.get("/api/v1/admin/alarm-names")).json()}
        dcpa = listed["DCPA_Missing"]
        assert dcpa["place"] == {"kind": "component", "site": "04", "component": "DCP"}
        assert dcpa["source"] == "seed" and dcpa["events"] == 2 and dcpa["type"] == "error"
        assert dcpa["last_seen"].startswith("2026-11-03T10:43:49")

        url = "/api/v1/admin/alarm-names/DCPA_Missing"
        r = await admin.send("PUT", url, {"kind": "site", "site": "04"})
        assert r.status_code == 200, r.text
        assert r.json()["place"] == {"kind": "site", "site": "04", "component": None}
        assert r.json()["source"] == "admin" and r.json()["updated_by"] == "al-admin"

        on_dcp = (await viewer.get(f"{SYS}/alarms?{DAY_Q}&scope=component:04:DCP")).json()["events"]
        at_site = (await viewer.get(f"{SYS}/alarms?{DAY_Q}&scope=site:04")).json()["events"]
        assert on_dcp == [] and "DCPA_Missing" in [e["name"] for e in at_site]
        entry = (await _audit(admin, "alarm_mapping_changed"))[0]
        assert entry["entity_id"] == "DCPA_Missing"
        assert entry["before"] == {"place": "component:04:DCP"} and entry["after"] == {"place": "site:04"}

        refused = await admin.send("PUT", url, {"kind": "component", "site": "04", "component": "LIGH"})
        assert refused.status_code == 422 and refused.json()["code"] == "component_not_found"
        unknown = await admin.send("PUT", "/api/v1/admin/alarm-names/NoSuchAlarm", {"kind": "station"})
        assert unknown.status_code == 404 and unknown.json()["code"] == "alarm_not_found"
        no_csrf = await admin.send("PUT", url, {"kind": "station"}, csrf=False)
        assert no_csrf.status_code == 403
        assert (await viewer.send("PUT", url, {"kind": "station"})).status_code == 403

        back = await admin.send("PUT", url, {"kind": "component", "site": "04", "component": "DCP"})
        assert back.status_code == 200
        assert back.json()["place"] == {"kind": "component", "site": "04", "component": "DCP"}


async def test_a_reprocess_can_read_the_alarm_files_only(engine: AsyncEngine, people: None) -> None:
    system = await _system(engine)
    ingestor = Cat3Ingestor(engine, system, get_settings())
    async with engine.begin() as conn:  # only one reprocess may be queued: clear what earlier tests left
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))
    async with Browser() as admin:
        assert (await admin.login("al-admin")).status_code == 200
        body = {"type": "reprocess", "from": "2026-11-03", "to": "2026-11-03"}
        none = await admin.send("POST", "/api/v1/admin/jobs", {**body, "sources": []})
        assert none.status_code == 422 and none.json()["code"] == "no_sources"
        r = await admin.send("POST", "/api/v1/admin/jobs", {**body, "sources": ["alarms"]})
        assert r.status_code == 201, r.text
        job = r.json()
        assert job["params"]["sources"] == ["alarms"]
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE job SET status = 'running' WHERE id = :id"), {"id": job["id"]})

        async def ingestor_for(_code: str) -> Cat3Ingestor:
            return ingestor

        await jobs.execute(
            engine, {"id": job["id"], "type": "reprocess", "params": job["params"]}, ingestor_for
        )
        done = (await admin.get(f"/api/v1/admin/jobs/{job['id']}")).json()
        assert done["status"] == "done", done
        assert done["message"] == "reprocessed 1 day(s) of alarm files; 0 new alarm row(s)"
        assert "alarms:CDP1=7" in done["log"] and "CDP1=" not in done["log"].replace("alarms:CDP1", "")
    assert jobs.reprocess_sources({}) == ["minutes", "alarms"]
    assert jobs.reprocess_sources({"sources": ["alarms", "minutes"]}) == ["minutes", "alarms"]
