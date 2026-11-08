"""Data-quality summary and definitions against a real database (R3.3, FR-DQ-008, FR-KPI-010).

R3.3 acceptance: the summary's minutes equal the flagged and detection minutes of the outage list for the same
period. A maintenance flag is put on 3 November 2026 (the day the pipeline tests load) and removed again at the end;
any confirmed detection left by other tests is checked the same way.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.core.config import get_settings
from simola.ingestion.cat3 import Cat3Ingestor
from simola.kpi import definitions
from simola.registry import load_system
from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

SYS = "/api/v1/systems/WIDN-CAT3"
Q = "from=2026-11-03T00:00:00Z&to=2026-11-04T00:00:00Z"
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
async def marked(engine: AsyncEngine) -> AsyncIterator[dict[str, int]]:
    """3 November loaded, with a maintenance flag on Runway 04's barometer."""
    async with engine.connect() as conn:
        system = await load_system(conn, "WIDN-CAT3")
    assert system is not None
    await Cat3Ingestor(engine, system, get_settings()).reprocess_day(date(2026, 11, 3), now=NOW)
    await _add_user(engine, "qs-admin", "admin")
    await _add_user(engine, "qs-viewer", "viewer")
    ids: dict[str, int] = {}
    async with Browser() as admin:
        assert (await admin.login("qs-admin")).status_code == 200
        comps = {
            f"{c['site']}:{c['type']}": c["id"] for c in (await admin.get("/api/v1/admin/components")).json()
        }
        r = await admin.send(
            "POST",
            "/api/v1/admin/flags",
            {
                "component_ids": [comps["04:BARO"]],
                "start": "2026-11-03T06:00:00Z",
                "end": "2026-11-03T07:30:00Z",
                "reason": "maintenance",
                "note": "data-quality test",
            },
        )
        assert r.status_code == 201, r.text
        ids["flag"] = r.json()["flag"]["id"] if "flag" in r.json() else r.json()["id"]
    yield ids
    async with Browser() as admin:
        assert (await admin.login("qs-admin")).status_code == 200
        await admin.send("DELETE", f"/api/v1/admin/flags/{ids['flag']}")
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))


async def test_the_summary_equals_the_outage_list(marked: dict[str, int]) -> None:
    async with Browser() as visitor:
        s = (await visitor.get(f"{SYS}/data-quality?{Q}")).json()
        assert s["definitions_version"] == definitions.VERSION
        assert s["pending_suspects"] is None  # the public sees no suspect count (D7)
        baro = next(c for c in s["components"] if (c["site"], c["component"]) == ("04", "BARO"))
        assert baro["flags"] == 1 and baro["reasons"][0]["kind"] == "flag"
        assert baro["reasons"][0]["reason"] == "maintenance"
        assert 0 < baro["flagged_minutes"] <= 90  # minutes already lost for another reason stay there
        assert s["flags"] >= 1 and s["flagged_minutes"] == sum(c["flagged_minutes"] for c in s["components"])
        # R3.3 acceptance: every sensor's minutes equal its outage list for the same period
        for c in s["components"]:
            o = (await visitor.get(f"{SYS}/outages?{Q}&scope=component:{c['site']}:{c['component']}")).json()
            assert c["flagged_minutes"] == o["by_cause"]["flagged"], c
            assert c["detection_minutes"] == o["by_cause"]["detection"], c
            assert c["expected"] == o["availability"]["expected"], c
        ola = (await visitor.get(f"{SYS}/outages?{Q}&scope=ola")).json()
        assert s["flagged_minutes"] == ola["by_cause"]["flagged"]
        assert s["detection_minutes"] == ola["by_cause"]["detection"]


async def test_signed_in_users_see_the_suspects_and_long_periods_are_refused(marked: dict[str, int]) -> None:
    async with Browser() as viewer:
        assert (await viewer.login("qs-viewer")).status_code == 200
        s = (await viewer.get(f"{SYS}/data-quality?{Q}")).json()
        assert isinstance(s["pending_suspects"], int)
        long = await viewer.get(f"{SYS}/data-quality?from=2026-01-01T00:00:00Z&to=2026-11-01T00:00:00Z")
        assert long.status_code == 422 and long.json()["code"] == "period_too_long"


async def test_the_definitions_version_is_public() -> None:
    async with Browser() as visitor:
        d = (await visitor.get("/api/v1/definitions")).json()
    assert d == {"version": definitions.VERSION, "effective_from": "2025-12-24", "source": definitions.SOURCE}
