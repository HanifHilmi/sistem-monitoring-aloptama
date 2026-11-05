"""Manual flags against a real database (R2.3, FR-DQ-006/007, FR-KPI-006/008/009, UAT U4).

U4: a 60-minute flag over valid data lowers that component's figures by exactly 60 minutes, everywhere the figure
appears, and removing the flag restores them. Every test removes its flags, so later tests see R1's figures.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.kpi.engine import recompute_days
from tests.integration.browser import Browser, _add_user
from tests.integration.test_admin_ops import _daily, _ingestor, run_queued

pytestmark = pytest.mark.integration

DAY = date(2026, 11, 3)
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
DAY_START = datetime(2026, 11, 3, tzinfo=UTC)
SYS = "/api/v1/systems/WIDN-CAT3"
SCOPE = "component:04:ATRH"
PERIOD = {"from": "2026-11-03T00:00:00Z", "to": "2026-11-04T00:00:00Z"}


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


@pytest.fixture(scope="module")
async def flagger(engine: AsyncEngine) -> AsyncIterator[str]:
    """One day of real data with its daily figures, and an Admin. Leaves no queued job behind."""
    ing = await _ingestor(engine)
    await ing.reprocess_day(DAY, now=NOW)
    async with engine.begin() as conn:
        await recompute_days(conn, ing.system, [DAY], NOW)
    await _add_user(engine, "flag-admin", "admin")
    await run_queued(engine)
    yield "flag-admin"
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))


async def _valid_hour(engine: AsyncEngine) -> datetime:
    """An hour of the day in which runway 04's ATRH is valid in every minute."""
    async with engine.connect() as conn:
        hour = await conn.scalar(
            text("""
            SELECT date_trunc('hour', time) FROM awos_cat3_minute
            WHERE site_id = (SELECT id FROM site WHERE slug = '04') AND time >= :a AND time < :b
              AND temp_c IS NOT NULL AND rh_pct IS NOT NULL
            GROUP BY 1 HAVING count(*) = 60 ORDER BY 1 LIMIT 1
        """),
            {"a": DAY_START, "b": DAY_START + timedelta(days=1)},
        )
    assert hour is not None, "the fixture day has no fully valid hour at runway 04"
    return hour  # type: ignore[no-any-return]


async def _ids(admin: Browser) -> dict[str, int]:
    rows = (await admin.get("/api/v1/admin/components")).json()
    return {f"{c['site']}:{c['type']}": c["id"] for c in rows}


async def _audit(admin: Browser, action: str) -> list[dict[str, Any]]:
    return list((await admin.get(f"/api/v1/admin/audit?action={action}")).json()["events"])


async def _figures(b: Browser) -> dict[str, Any]:
    minutes = (await b.get(f"{SYS}/minutes", params={"day": DAY.isoformat(), "scope": SCOPE})).json()
    outages = (await b.get(f"{SYS}/outages", params={**PERIOD, "scope": SCOPE})).json()
    matrix = (await b.get(f"{SYS}/matrix", params={**PERIOD, "bucket": "day"})).json()
    row = next(r for r in matrix["rows"] if r["key"] == SCOPE)
    return {"minutes": minutes, "outages": outages, "matrix": matrix, "row": row["total"]}


async def test_u4_a_60_minute_flag_costs_exactly_60_minutes_and_removing_it_restores_them(
    engine: AsyncEngine, flagger: str
) -> None:
    start = await _valid_hour(engine)
    end = start + timedelta(hours=1)
    before = await _daily(engine, "04", "ATRH")
    dcp_before = await _daily(engine, "04", "DCP")
    async with Browser() as admin, Browser() as visitor:
        await admin.login(flagger)
        ids = await _ids(admin)
        atrh = ids["04:ATRH"]

        preview = await admin.get(
            "/api/v1/admin/flags/preview",
            params={"components": str(atrh), "from": iso(start), "to": iso(end)},
        )
        assert preview.status_code == 200
        assert preview.json()["components"] == [
            {"id": atrh, "site": "04", "type": "ATRH", "minutes": 60, "lost": 60, "already": 0}
        ]
        assert preview.json()["days"] == {"from": DAY.isoformat(), "to": DAY.isoformat()}

        draft = {
            "component_ids": [atrh],
            "start": iso(start),
            "end": iso(end),
            "reason": "maintenance",
            "note": "Cable replaced; readings unstable while the work went on.",
        }
        created = await admin.send("POST", "/api/v1/admin/flags", draft)
        assert created.status_code == 201, created.text
        flag, job = created.json()["flag"], created.json()["job"]
        assert flag["components"] == [{"site": "04", "type": "ATRH"}] and flag["component_ids"] == [atrh]
        assert flag["created_by"] == flagger and flag["removed_at"] is None
        assert job["type"] == "recompute" and job["params"]["from"] == job["params"]["to"] == DAY.isoformat()

        # Everyone sees the flag and its reason; only signed-in users see the note and who made it.
        public = (await visitor.get(f"{SYS}/flags", params={**PERIOD, "scope": SCOPE})).json()
        assert [(f["id"], f["reason"]) for f in public] == [(flag["id"], "maintenance")]
        assert "note" not in public[0] and "created_by" not in public[0]
        signed_in = (await admin.get(f"{SYS}/flags", params={**PERIOD, "scope": SCOPE})).json()
        assert signed_in[0]["note"] == draft["note"] and signed_in[0]["created_by"] == flagger
        assert (
            await visitor.get(f"{SYS}/flags", params={**PERIOD, "scope": "component:22:ATRH"})
        ).json() == []

        waiting = await _figures(visitor)
        assert waiting["matrix"]["period"]["recalculating"] == [
            {"from": DAY.isoformat(), "to": DAY.isoformat()}
        ]
        assert job["id"] in await run_queued(engine)

        # U4: exactly 60 minutes fewer, in the stored day, the matrix, the minute view and the outage list.
        assert await _daily(engine, "04", "ATRH") == (before[0] - 60, before[1])
        assert await _daily(engine, "04", "DCP") == dcp_before  # DCP is never affected
        after = await _figures(visitor)
        assert after["matrix"]["period"]["recalculating"] == []
        assert after["row"]["valid"] == before[0] - 60
        assert after["minutes"]["valid"] == before[0] - 60 and after["minutes"]["codes"].count("g") == 60
        flagged = [i for i in after["minutes"]["intervals"] if i["cause"] == "flagged"]
        assert [(i["minutes"], i["flags"]) for i in flagged] == [
            (60, [{"id": flag["id"], "reason": "maintenance"}])
        ]
        assert after["outages"]["by_cause"]["flagged"] == 60
        assert sum(after["outages"]["by_cause"].values()) == after["outages"]["availability"]["missing"]
        assert any(
            i.get("flags") == [{"id": flag["id"], "reason": "maintenance"}]
            for i in after["outages"]["intervals"]
        )

        # A change of reason or note is audited but leaves the figures alone; a DCP is refused.
        edited = await admin.send(
            "PATCH",
            f"/api/v1/admin/flags/{flag['id']}",
            {**draft, "reason": "sensor_fault", "note": "Wrong cable."},
        )
        assert edited.status_code == 200 and edited.json()["job"] is None
        assert edited.json()["flag"]["updated_by"] == flagger
        change = (await _audit(admin, "flag_updated"))[0]
        assert change["before"] == {"reason": "maintenance", "note": draft["note"]}
        assert change["after"] == {"reason": "sensor_fault", "note": "Wrong cable."}
        dcp = await admin.send(
            "PATCH", f"/api/v1/admin/flags/{flag['id']}", {**draft, "component_ids": [atrh, ids["04:DCP"]]}
        )
        assert dcp.status_code == 422 and dcp.json()["code"] == "dcp_cannot_be_flagged"

        # Removing it restores the figures; the flag stays, marked removed, and in the audit log.
        removed = await admin.send("DELETE", f"/api/v1/admin/flags/{flag['id']}")
        assert removed.status_code == 200 and removed.json()["flag"]["removed_by"] == flagger
        await run_queued(engine)
        assert await _daily(engine, "04", "ATRH") == before
        restored = await _figures(visitor)
        assert (
            restored["minutes"]["codes"].count("g") == 0 and restored["outages"]["by_cause"]["flagged"] == 0
        )
        again = await admin.send("DELETE", f"/api/v1/admin/flags/{flag['id']}")
        assert again.status_code == 409 and again.json()["code"] == "flag_removed"
        assert flag["id"] not in [f["id"] for f in (await admin.get("/api/v1/admin/flags")).json()]
        listed = (await admin.get("/api/v1/admin/flags", params={"removed": "true"})).json()
        assert next(f for f in listed if f["id"] == flag["id"])["removed_at"] is not None
        assert (await visitor.get(f"{SYS}/flags", params=PERIOD)).json() == []
        assert (await _audit(admin, "flag_created"))[0]["entity_id"] == str(flag["id"])
        assert (await _audit(admin, "flag_removed"))[0]["before"]["components"] == ["04:ATRH"]
        async with engine.connect() as conn:
            left = await conn.scalar(
                text("SELECT count(*) FROM invalid_interval WHERE source = 'flag' AND source_id = :id"),
                {"id": flag["id"]},
            )
        assert left == 0


async def test_overlapping_flags_count_each_minute_once(engine: AsyncEngine, flagger: str) -> None:
    """E9: two flags over the same hour lower the figure by 60 minutes, not 120; the older flag owns them."""
    start = await _valid_hour(engine)
    before = await _daily(engine, "04", "ATRH")
    async with Browser() as admin:
        await admin.login(flagger)
        atrh = (await _ids(admin))["04:ATRH"]
        made = []
        for minutes, reason in ((60, "calibration"), (30, "other")):
            r = await admin.send(
                "POST",
                "/api/v1/admin/flags",
                {
                    "component_ids": [atrh],
                    "start": iso(start),
                    "end": iso(start + timedelta(minutes=minutes)),
                    "reason": reason,
                    "note": "Overlap test.",
                },
            )
            assert r.status_code == 201, r.text
            made.append(r.json()["flag"]["id"])
        # The second flag on its own would cost nothing more: the first already covers it.
        preview = await admin.get(
            "/api/v1/admin/flags/preview",
            params={"components": str(atrh), "from": iso(start), "to": iso(start + timedelta(minutes=30))},
        )
        assert (
            preview.json()["components"][0]["lost"] == 0 and preview.json()["components"][0]["already"] == 30
        )
        await run_queued(engine)
        assert await _daily(engine, "04", "ATRH") == (before[0] - 60, before[1])
        outages = (await admin.get(f"{SYS}/outages", params={**PERIOD, "scope": SCOPE})).json()
        owners = {i["flags"][0]["id"] for i in outages["intervals"] if i["cause"] == "flagged"}
        assert outages["by_cause"]["flagged"] == 60 and owners == {made[0]}
        for fid in made:
            assert (await admin.send("DELETE", f"/api/v1/admin/flags/{fid}")).status_code == 200
        await run_queued(engine)
        assert await _daily(engine, "04", "ATRH") == before


async def test_flags_that_are_refused(engine: AsyncEngine, flagger: str) -> None:
    async with Browser() as admin:
        await admin.login(flagger)
        atrh = (await _ids(admin))["04:ATRH"]
        soon = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=5)
        base = {"component_ids": [atrh], "reason": "other", "note": "Refusal test."}
        for change, code in (
            ({"start": iso(soon - timedelta(hours=1)), "end": iso(soon)}, "flag_in_future"),
            ({"start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z"}, "before_coverage"),
            ({"start": "2026-11-03T02:00:00Z", "end": "2026-11-03T01:00:00Z"}, "invalid_period"),
            ({"start": "2026-11-03T01:00:00Z", "end": "2026-11-03T02:00:00Z", "note": "x"}, "note_required"),
            (
                {"start": "2026-11-03T01:00:00Z", "end": "2026-11-03T02:00:00Z", "component_ids": []},
                "no_components",
            ),
        ):
            r = await admin.send("POST", "/api/v1/admin/flags", {**base, **change})
            assert r.status_code == 422 and r.json()["code"] == code, (change, r.text)
        missing = await admin.send(
            "PATCH",
            "/api/v1/admin/flags/999999",
            {**base, "start": "2026-11-03T01:00:00Z", "end": "2026-11-03T02:00:00Z"},
        )
        assert missing.status_code == 404 and missing.json()["code"] == "flag_not_found"
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM flag WHERE note = 'Refusal test.'")) == 0
