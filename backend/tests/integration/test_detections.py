"""Validity rules and detections against a real database (R2.4, FR-DQ-001..005, UAT U3).

A range rule on runway 04's relative humidity fires on the day's highest readings. Suspects change nothing; once
confirmed they lower ATRH's figures by exactly the minutes that were otherwise valid; rejecting them restores the
figures; running the rules again gives the same detections. Everything is rejected and the rule turned off at the
end, so the pipeline tests that follow see R1's figures.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.dq.history import propose_rules
from simola.kpi.engine import recompute_days
from simola.registry import load_system
from simola.worker import jobs
from tests.integration.browser import Browser, _add_user
from tests.integration.test_admin_ops import _daily, _ingestor, run_queued

pytestmark = pytest.mark.integration

DAY = date(2026, 11, 3)
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
DAY_START = datetime(2026, 11, 3, tzinfo=UTC)
SYS = "/api/v1/systems/WIDN-CAT3"
SCOPE = "component:04:ATRH"
PERIOD = {"from": "2026-11-03T00:00:00Z", "to": "2026-11-04T00:00:00Z"}


@pytest.fixture(scope="module")
async def reviewer(engine: AsyncEngine) -> AsyncIterator[str]:
    ing = await _ingestor(engine)
    await ing.reprocess_day(DAY, now=NOW)
    async with engine.begin() as conn:
        await recompute_days(conn, ing.system, [DAY], NOW)
    await _add_user(engine, "dq-admin", "admin")
    await run_queued(engine)
    yield "dq-admin"
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))


async def _rh(engine: AsyncEngine) -> tuple[float, int, int]:
    """A limit just under the day's highest RH at runway 04, the minutes above it, and of those the ones ATRH
    would otherwise count as valid (TEMP present too)."""
    async with engine.connect() as conn:
        args = {"a": DAY_START, "b": DAY_START + timedelta(days=1)}
        site = "(SELECT id FROM site WHERE slug = '04')"
        top = await conn.scalar(
            text(
                f"SELECT max(rh_pct) FROM awos_cat3_minute WHERE site_id = {site} AND time >= :a AND time < :b"
            ),
            args,
        )
        limit = float(top) - 0.5
        above, valid = (
            await conn.execute(
                text(f"""
            SELECT count(*), count(*) FILTER (WHERE temp_c IS NOT NULL) FROM awos_cat3_minute
            WHERE site_id = {site} AND time >= :a AND time < :b AND rh_pct > :x
        """),
                {**args, "x": limit},
            )
        ).one()
    assert above > 0
    return limit, int(above), int(valid)


async def _queue(admin: Browser, status: str) -> dict[str, Any]:
    r = await admin.get("/api/v1/admin/detections", params={"status": status, "site": "04", "field": "RH"})
    assert r.status_code == 200, r.text
    return dict(r.json())


async def _snapshot(engine: AsyncEngine, rule_id: int) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
            SELECT id, rule_version, start_at, end_at, status, evidence::text FROM dq_detection
            WHERE rule_id = :r ORDER BY start_at, id
        """),
            {"r": rule_id},
        )
        return [tuple(r) for r in rows]


async def test_u3_suspects_change_nothing_confirmed_ones_cost_exactly_their_minutes(
    engine: AsyncEngine, reviewer: str
) -> None:
    limit, above, lost = await _rh(engine)
    before = await _daily(engine, "04", "ATRH")
    dcp_before = await _daily(engine, "04", "DCP")
    async with Browser() as admin, Browser() as visitor:
        await admin.login(reviewer)

        dry = await admin.get(
            "/api/v1/admin/rules/dry-run",
            params={
                "component_type": "ATRH",
                "field": "RH",
                "site": "04",
                "type": "range",
                "params": json.dumps({"max": limit}),
            },
        )
        assert dry.status_code == 200 and set(dry.json()) >= {"intervals", "minutes", "sites", "examples"}

        made = await admin.send(
            "POST",
            "/api/v1/admin/rules",
            {
                "component_type": "ATRH",
                "field": "RH",
                "site": "04",
                "type": "range",
                "params": {"max": limit},
                "enabled": True,
            },
        )
        assert made.status_code == 201, made.text
        rule, job = made.json()["rule"], made.json()["job"]
        assert rule["version"] == 1 and rule["site"] == "04" and rule["mandatory"] and not rule["proposed"]
        assert job["type"] == "detect" and job["params"]["rule_id"] == rule["id"]
        again = await admin.send(
            "POST",
            "/api/v1/admin/rules",
            {"component_type": "ATRH", "field": "RH", "site": "04", "type": "range", "params": {"max": 1}},
        )
        assert again.status_code == 409 and again.json()["code"] == "rule_exists"
        await run_queued(engine)

        # Suspects: the minutes above the limit, visible to signed-in users only, and the figures unchanged.
        queue = await _queue(admin, "suspect")
        assert queue["counts"]["suspect"] >= 1
        assert sum(d["minutes"] for d in queue["detections"]) == above
        assert all(d["rule_version"] == 1 and d["mandatory"] for d in queue["detections"])
        assert (await visitor.get(f"{SYS}/detections", params={**PERIOD, "scope": SCOPE})).json() == []
        assert len((await admin.get(f"{SYS}/detections", params={**PERIOD, "scope": SCOPE})).json()) == len(
            queue["detections"]
        )
        seen = (await admin.get(f"{SYS}/minutes", params={"day": DAY.isoformat(), "scope": SCOPE})).json()
        assert seen["codes"].count("s") == lost and seen["valid"] == before[0]
        hidden = (await visitor.get(f"{SYS}/minutes", params={"day": DAY.isoformat(), "scope": SCOPE})).json()
        assert "s" not in hidden["codes"]
        assert await _daily(engine, "04", "ATRH") == before
        problems = (await admin.get(f"{SYS}/problems")).json()["problems"]
        assert any(p["code"] == "suspects_pending" and p["link"] == "/admin/review" for p in problems)
        assert not any(
            p["code"] == "suspects_pending" for p in (await visitor.get(f"{SYS}/problems")).json()["problems"]
        )

        # Running the rules again changes nothing (FR-DQ-003.1).
        snapshot = await _snapshot(engine, rule["id"])
        await jobs.enqueue(
            engine, "detect", {"system": "WIDN-CAT3", "from": DAY.isoformat(), "to": DAY.isoformat()}
        )
        await run_queued(engine)
        assert await _snapshot(engine, rule["id"]) == snapshot

        # Confirmed: exactly the otherwise-valid minutes are lost, everywhere the figure appears.
        ids = [d["id"] for d in queue["detections"]]
        decided = await admin.send(
            "POST",
            "/api/v1/admin/detections/decide",
            {"ids": ids, "decision": "confirm", "note": "Wet sensor."},
        )
        assert decided.status_code == 200, decided.text
        assert {d["status"] for d in decided.json()["decided"]} == {"confirmed"}
        assert decided.json()["job"]["type"] == "recompute"
        await run_queued(engine)
        assert await _daily(engine, "04", "ATRH") == (before[0] - lost, before[1])
        assert await _daily(engine, "04", "DCP") == dcp_before  # DCP is never affected
        outages = (await visitor.get(f"{SYS}/outages", params={**PERIOD, "scope": SCOPE})).json()
        assert outages["by_cause"]["detection"] == lost
        assert sum(outages["by_cause"].values()) == outages["availability"]["missing"]
        minutes = (
            await visitor.get(f"{SYS}/minutes", params={"day": DAY.isoformat(), "scope": SCOPE})
        ).json()
        assert minutes["codes"].count("d") == lost and minutes["valid"] == before[0] - lost
        public = (await visitor.get(f"{SYS}/detections", params={**PERIOD, "scope": SCOPE})).json()
        assert {d["status"] for d in public} == {"confirmed"} and "note" not in public[0]

        # Running the rules again keeps the decisions.
        await jobs.enqueue(
            engine, "detect", {"system": "WIDN-CAT3", "from": DAY.isoformat(), "to": DAY.isoformat()}
        )
        await run_queued(engine)
        assert {r[4] for r in await _snapshot(engine, rule["id"])} == {"confirmed"}

        # A rule change makes version 2; the decided detections keep version 1 (PRD E8).
        changed = await admin.send(
            "PUT",
            f"/api/v1/admin/rules/{rule['id']}",
            {
                "component_type": "ATRH",
                "field": "RH",
                "site": "04",
                "type": "range",
                "params": {"max": limit + 0.25},
                "enabled": True,
            },
        )
        assert changed.status_code == 200 and changed.json()["rule"]["version"] == 2 and changed.json()["job"]
        versions = (await admin.get(f"/api/v1/admin/rules/{rule['id']}/versions")).json()
        assert [v["version"] for v in versions] == [2, 1]
        await run_queued(engine)
        assert {r[1] for r in await _snapshot(engine, rule["id"]) if r[4] == "confirmed"} == {1}

        # Rejecting restores the figures; the decisions are audited one by one.
        every = [r[0] for r in await _snapshot(engine, rule["id"])]
        undone = await admin.send(
            "POST", "/api/v1/admin/detections/decide", {"ids": every, "decision": "reject"}
        )
        assert undone.status_code == 200
        await run_queued(engine)
        assert await _daily(engine, "04", "ATRH") == before
        audit = (await admin.get("/api/v1/admin/audit", params={"action": "detections_decided"})).json()[
            "events"
        ]
        assert audit[0]["after"]["status"] == "rejected"
        assert any(e["before"] == {"status": "confirmed"} for e in audit)

        off = await admin.send(
            "PUT",
            f"/api/v1/admin/rules/{rule['id']}",
            {
                "component_type": "ATRH",
                "field": "RH",
                "site": "04",
                "type": "range",
                "params": {"max": limit + 0.25},
                "enabled": False,
            },
        )
        assert off.status_code == 200 and off.json()["job"] is None and not off.json()["rule"]["enabled"]
        assert (await _queue(admin, "confirmed"))["counts"]["confirmed"] == 0


async def test_rules_that_are_refused_and_proposals_from_the_history(
    engine: AsyncEngine, reviewer: str
) -> None:
    async with Browser() as admin:
        await admin.login(reviewer)
        base = {"component_type": "ATRH", "field": "TEMP", "type": "range", "params": {"min": 10, "max": 45}}
        for change, code in (
            ({"component_type": "XYZ"}, "component_type_not_found"),
            ({"field": "QNH"}, "unknown_field"),
            ({"component_type": "PWX", "field": "PW"}, "text_field"),
            ({"site": "22", "component_type": "RVR", "field": "ALS"}, "site_has_no_field"),
            ({"params": {}}, "range_needs_a_limit"),
            ({"type": "stuck", "params": {"minutes": 2}}, "invalid_minutes"),
        ):
            r = await admin.send("POST", "/api/v1/admin/rules", {**base, **change})
            assert r.status_code == 422 and r.json()["code"] == code, (change, r.text)

        hist = await admin.get(
            "/api/v1/admin/rules/history", params={"component_type": "ATRH", "field": "TEMP"}
        )
        assert hist.status_code == 200, hist.text
        h = hist.json()
        assert (
            h["minutes"] > 0 and h["p001"] <= h["p999"] and set(h["proposed"]) == {"range", "stuck", "spike"}
        )

    async with engine.begin() as conn:
        system = await load_system(conn, "WIDN-CAT3")
        assert system is not None
        made = await propose_rules(conn, system)
    assert made and all(m["params"] for m in made)
    async with Browser() as admin:
        await admin.login(reviewer)
        listed = (await admin.get("/api/v1/admin/rules")).json()
        proposed = [r for r in listed if r["proposed"]]
        assert proposed and not any(r["enabled"] for r in proposed)  # off until approved (OPEN-08)
        temp = next(
            r
            for r in proposed
            if r["component_type"] == "ATRH" and r["field"] == "TEMP" and r["type"] == "range"
        )
        approved = await admin.send(
            "PUT",
            f"/api/v1/admin/rules/{temp['id']}",
            {
                "component_type": "ATRH",
                "field": "TEMP",
                "type": "range",
                "params": temp["params"],
                "enabled": False,
            },
        )
        assert approved.status_code == 200 and not approved.json()["rule"]["proposed"]  # reviewed, still off
