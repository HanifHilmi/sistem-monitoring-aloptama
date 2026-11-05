"""Admin operations against a real database (R2.2): jobs, settings, mandatory fields, in-service periods.

Every test puts things back (default rules, no queued job) so the pipeline tests that follow see R1's state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.core.config import get_settings
from simola.ingestion.cat3 import Cat3Ingestor
from simola.kpi.engine import recompute_days
from simola.registry import load_system
from simola.worker import jobs
from simola.worker.main import Worker
from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

DAY = date(2026, 11, 3)
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
DAY_START = datetime(2026, 11, 3, tzinfo=UTC)


async def _ingestor(engine: AsyncEngine, code: str = "WIDN-CAT3") -> Cat3Ingestor:
    async with engine.connect() as conn:
        system = await load_system(conn, code)
    assert system is not None
    return Cat3Ingestor(engine, system, get_settings())


async def run_queued(engine: AsyncEngine) -> list[int]:
    """Runs every queued job the way the worker does."""

    async def ingestor_for(code: str) -> Cat3Ingestor:
        return await _ingestor(engine, code)

    ran = []
    while (job := await jobs.claim(engine)) is not None:
        await jobs.execute(engine, job, ingestor_for)
        ran.append(int(job["id"]))
    return ran


async def _daily(engine: AsyncEngine, slug: str, type_code: str) -> tuple[int, int]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("""
            SELECT d.valid, d.expected FROM availability_daily d
            JOIN component c ON c.id = d.scope_id JOIN site s ON s.id = c.site_id
            WHERE d.scope_type = 'component' AND s.slug = :slug AND c.type_code = :t AND d.day = :day
        """),
                {"slug": slug, "t": type_code, "day": DAY},
            )
        ).one()
    return int(row.valid), int(row.expected)


@pytest.fixture(scope="module")
async def ops(engine: AsyncEngine) -> AsyncIterator[str]:
    """One day of real data with its daily figures, and an Admin. Leaves no queued job behind."""
    ing = await _ingestor(engine)
    await ing.reprocess_day(DAY, now=NOW)
    async with engine.begin() as conn:
        await recompute_days(conn, ing.system, [DAY], NOW)
    await _add_user(engine, "ops-admin", "admin")
    yield "ops-admin"
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))


async def _audit(admin: Browser, action: str) -> list[dict[str, Any]]:
    return list((await admin.get(f"/api/v1/admin/audit?action={action}")).json()["events"])


async def test_jobs_start_list_cancel_and_one_reprocess_at_a_time(engine: AsyncEngine, ops: str) -> None:
    async with Browser() as admin:
        await admin.login(ops)
        day = {"from": DAY.isoformat(), "to": DAY.isoformat()}
        recompute = await admin.send("POST", "/api/v1/admin/jobs", {"type": "recompute", **day})
        assert recompute.status_code == 201 and recompute.json()["created_by"] == ops
        assert recompute.json()["params"]["from"] == DAY.isoformat()
        first = await admin.send("POST", "/api/v1/admin/jobs", {"type": "reprocess", **day})
        second = await admin.send("POST", "/api/v1/admin/jobs", {"type": "reprocess", **day})
        assert first.status_code == 201
        assert second.status_code == 409 and second.json()["code"] == "job_running"

        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        for body, code in (
            ({"type": "recompute", "from": "2026-11-04", "to": "2026-11-03"}, "invalid_period"),
            ({"type": "recompute", "from": DAY.isoformat(), "to": tomorrow}, "future_days"),
            ({"type": "recompute", "from": "2025-01-01", "to": DAY.isoformat()}, "before_coverage"),
        ):
            r = await admin.send("POST", "/api/v1/admin/jobs", body)
            assert r.status_code == 422 and r.json()["code"] == code, body

        cancel = await admin.send("POST", f"/api/v1/admin/jobs/{first.json()['id']}/cancel")
        assert cancel.status_code == 200 and cancel.json()["status"] == "cancelled"
        again = await admin.send("POST", f"/api/v1/admin/jobs/{first.json()['id']}/cancel")
        assert again.status_code == 409 and again.json()["code"] == "job_not_active"

        assert recompute.json()["id"] in await run_queued(engine)
        done = (await admin.get(f"/api/v1/admin/jobs/{recompute.json()['id']}")).json()
        assert done["status"] == "done" and done["progress"] == 1 and DAY.isoformat() in done["log"]
        listed = [j["id"] for j in (await admin.get("/api/v1/admin/jobs")).json()]
        assert listed[:2] == [first.json()["id"], recompute.json()["id"]]  # newest first
        assert len(await _audit(admin, "job_started")) >= 2 and await _audit(admin, "job_cancelled")


async def test_settings_are_validated_saved_audited_and_public(engine: AsyncEngine, ops: str) -> None:
    async with Browser() as admin:
        await admin.login(ops)
        doc = (await admin.get("/api/v1/admin/settings")).json()
        assert doc["grace_minutes"] == 3 and doc["color_thresholds"] == {"good": 99, "warning": 95}
        assert set(doc["problem_thresholds"]) == {
            "cdp_no_data_min",
            "cdp_unreachable_min",
            "site_no_data_min",
            "field_missing_min",
            "ingest_lag_min",
        }
        assert doc["changed"] == {}

        r = await admin.send("PUT", "/api/v1/admin/settings/grace_minutes", {"value": 4})
        assert r.status_code == 200 and r.json()["grace_minutes"] == 4
        assert r.json()["changed"]["grace_minutes"]["by"] == ops
        bad = await admin.send(
            "PUT", "/api/v1/admin/settings/color_thresholds", {"value": {"good": 95, "warning": 99}}
        )
        assert bad.status_code == 422 and bad.json()["code"] == "invalid_setting"
        r = await admin.send(
            "PUT", "/api/v1/admin/settings/color_thresholds", {"value": {"good": 99.5, "warning": 97}}
        )
        assert r.status_code == 200
        problems = {**doc["problem_thresholds"], "cdp_no_data_min": 3}
        assert (
            await admin.send("PUT", "/api/v1/admin/settings/problem_thresholds", {"value": problems})
        ).status_code == 200

        public = (await admin.get("/api/v1/settings/display")).json()
        assert public["grace_minutes"] == 4 and public["color_thresholds"] == {"good": 99.5, "warning": 97}
        async with engine.connect() as conn:
            stored = await conn.scalar(text("SELECT value FROM setting WHERE key = 'problem_thresholds'"))
        assert (
            stored["cdp_no_data_min"] == 3 and "backup_overdue_h" in stored
        )  # keys the page does not edit stay
        changed = await _audit(admin, "setting_changed")
        grace = next(e for e in changed if e["entity_id"] == "grace_minutes")
        assert grace["before"] == {"grace_minutes": 3} and grace["after"] == {"grace_minutes": 4}

        for key, value in (
            ("grace_minutes", 3),
            ("color_thresholds", doc["color_thresholds"]),
            ("problem_thresholds", doc["problem_thresholds"]),
        ):
            assert (
                await admin.send("PUT", f"/api/v1/admin/settings/{key}", {"value": value})
            ).status_code == 200


async def test_mandatory_fields_change_the_figures_through_a_recompute(engine: AsyncEngine, ops: str) -> None:
    """Ten minutes without a dew point at runway 04: making DEWP mandatory removes exactly those minutes."""
    async with engine.begin() as conn:
        site = await conn.scalar(text("SELECT id FROM site WHERE slug = '04'"))
        window = {"s": site, "a": DAY_START, "b": DAY_START + timedelta(minutes=10)}
        hit = await conn.scalar(
            text("""
            SELECT count(*) FROM awos_cat3_minute
            WHERE site_id = :s AND time >= :a AND time < :b AND temp_c IS NOT NULL AND rh_pct IS NOT NULL
              AND dewp_c IS NOT NULL
        """),
            window,
        )
        await conn.execute(
            text("UPDATE awos_cat3_minute SET dewp_c = NULL WHERE site_id = :s AND time >= :a AND time < :b"),
            window,
        )
    assert hit > 0
    before = await _daily(engine, "04", "ATRH")
    worker = Worker(get_settings(), engine)
    await worker.load()

    async with Browser() as admin:
        await admin.login(ops)
        types = {t["type"]: t for t in (await admin.get("/api/v1/admin/mandatory-fields")).json()}
        assert [f["code"] for f in types["ATRH"]["fields"] if f["mandatory"]] == ["TEMP", "RH"]
        assert types["DCP"]["is_dcp"]
        preview = await admin.get("/api/v1/admin/mandatory-fields/ATRH/preview?fields=TEMP,DEWP,RH")
        assert preview.status_code == 200 and len(preview.json()["sites"]) == 3
        for s in preview.json()["sites"]:
            assert s["proposed"]["valid"] <= s["current"]["valid"]
        refused = await admin.send("PUT", "/api/v1/admin/mandatory-fields/RVR", {"fields": ["ALS"]})
        assert refused.status_code == 422 and refused.json()["code"] == "no_mandatory_at_site"

        saved = await admin.send(
            "PUT", "/api/v1/admin/mandatory-fields/ATRH", {"fields": ["TEMP", "DEWP", "RH"]}
        )
        assert saved.status_code == 200 and saved.json()["job"]["type"] == "recompute"
        await worker.refresh_registry()
        atrh = next(c for s in worker.systems[0].sites for c in s.components if c.type_code == "ATRH")
        assert atrh.mandatory == ("TEMP", "DEWP", "RH")  # the worker reloaded the new rule by itself
        await run_queued(engine)
        after = await _daily(engine, "04", "ATRH")
        assert after == (before[0] - hit, before[1])

        restored = await admin.send("PUT", "/api/v1/admin/mandatory-fields/ATRH", {"fields": ["TEMP", "RH"]})
        assert restored.status_code == 200
        await run_queued(engine)
        assert await _daily(engine, "04", "ATRH") == before
        changes = await _audit(admin, "mandatory_changed")
        assert changes[0]["after"] == {"fields": ["TEMP", "RH"]} and changes[1]["after"]["fields"] == [
            "TEMP",
            "DEWP",
            "RH",
        ]


async def test_in_service_period_changes_the_expected_minutes(engine: AsyncEngine, ops: str) -> None:
    before = await _daily(engine, "04", "BARO")
    assert before[1] == 1440
    async with Browser() as admin:
        await admin.login(ops)
        rows = (await admin.get("/api/v1/admin/components")).json()
        assert len(rows) == 21
        baro = next(c for c in rows if c["site"] == "04" and c["type"] == "BARO")
        dcp = next(c for c in rows if c["site"] == "04" and c["is_dcp"])
        noon = "2026-11-03T12:00:00Z"

        r = await admin.send("PATCH", f"/api/v1/admin/components/{baro['id']}", {"in_service_from": noon})
        assert r.status_code == 200 and r.json()["component"]["in_service_from"].startswith(
            "2026-11-03T12:00"
        )
        assert (
            r.json()["job"]["params"]["to"] == DAY.isoformat()
        )  # days before installation change, later ones don't
        await run_queued(engine)
        valid, expected = await _daily(engine, "04", "BARO")
        assert expected == 720 and valid <= before[0]

        assert (
            await admin.send("PATCH", f"/api/v1/admin/components/{dcp['id']}", {"in_service_to": noon})
        ).json()["code"] == "dcp_has_no_period"
        wrong = await admin.send(
            "PATCH", f"/api/v1/admin/components/{baro['id']}", {"in_service_to": "2026-11-03T06:00:00Z"}
        )
        assert wrong.status_code == 422 and wrong.json()["code"] == "invalid_period"
        same = await admin.send("PATCH", f"/api/v1/admin/components/{baro['id']}", {"in_service_from": noon})
        assert same.json()["job"] is None  # nothing changed, nothing to recompute

        back = await admin.send("PATCH", f"/api/v1/admin/components/{baro['id']}", {"in_service_from": None})
        assert back.status_code == 200 and back.json()["component"]["in_service_from"] is None
        await run_queued(engine)
        assert await _daily(engine, "04", "BARO") == before
        changes = await _audit(admin, "in_service_changed")
        assert changes[0]["entity_id"] == "04:BARO" and changes[0]["after"]["in_service_from"] is None
