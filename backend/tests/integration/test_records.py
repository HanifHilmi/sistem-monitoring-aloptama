"""Records and calibration against a real database (R2.5, FR-REG-004/005, FR-AUD-003, UAT U5).

U5: recording a calibration gives the right status on every page that shows it; an overdue one is a Problems item;
serial and part numbers are hidden from the public; the figure trace lists a flag on the component. The tests put
every record back as they found it.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.cli import _cmd_import_records
from simola.records_import import ImportDoc, ImportRefused, run_import
from simola.registry import load_system
from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

SYS = "/api/v1/systems/WIDN-CAT3"
EMPTY_META = {
    "sensor_type": None,
    "manufacturer": None,
    "model": None,
    "part_number": None,
    "serial_number": None,
    "installed_on": None,
    "firmware": None,
    "notes": None,
}


def _today() -> date:
    return datetime.now(UTC).date()


@pytest.fixture(scope="module")
async def recorder(engine: AsyncEngine) -> AsyncIterator[str]:
    await _add_user(engine, "rec-admin", "admin")
    await _add_user(engine, "rec-viewer", "viewer")
    yield "rec-admin"
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job SET status = 'cancelled' WHERE status IN ('queued', 'running')"))


async def _ids(admin: Browser) -> dict[str, dict[str, Any]]:
    rows = (await admin.get("/api/v1/admin/components")).json()
    return {f"{c['site']}:{c['type']}": c for c in rows}


async def _audit(admin: Browser, action: str) -> list[dict[str, Any]]:
    return list((await admin.get(f"/api/v1/admin/audit?action={action}")).json()["events"])


async def _asset(b: Browser, key: str) -> dict[str, Any]:
    site, type_ = key.split(":")
    assets = (await b.get(f"{SYS}/assets")).json()
    return next(c for c in assets["components"] if c["site"] == site and c["type"] == type_)


async def _overdue(b: Browser) -> list[dict[str, Any]]:
    problems = (await b.get(f"{SYS}/problems")).json()["problems"]
    return [p for p in problems if p["code"] == "calibration_overdue"]


async def test_u5_calibration_status_problems_and_hidden_serials(engine: AsyncEngine, recorder: str) -> None:
    today = _today()
    async with Browser() as admin, Browser() as viewer, Browser() as visitor:
        assert (await admin.login(recorder)).status_code == 200
        assert (await viewer.login("rec-viewer")).status_code == 200
        rows = await _ids(admin)
        atrh, dcp = rows["04:ATRH"], rows["04:DCP"]
        assert atrh["calibration"] == {
            "status": "unknown",
            "last": None,
            "next_due": None,
            "days_left": None,
            "validated_on": None,
            "pending": False,
        }
        assert atrh["meta"] == EMPTY_META

        # The sensor's record: everyone sees the model, only signed-in users the serial and part numbers.
        meta = {
            **EMPTY_META,
            "manufacturer": " Vaisala ",
            "model": "HMP155",
            "serial_number": "SN-0001",
            "part_number": "PN-77",
            "installed_on": "2024-03-01",
        }
        saved = await admin.send("PUT", f"/api/v1/admin/components/{atrh['id']}/meta", meta)
        assert saved.status_code == 200, saved.text
        assert saved.json()["manufacturer"] == "Vaisala" and saved.json()["serial_number"] == "SN-0001"
        public = await _asset(visitor, "04:ATRH")
        assert public["meta"]["model"] == "HMP155"
        assert "serial_number" not in public["meta"] and "part_number" not in public["meta"]
        signed_in = await _asset(viewer, "04:ATRH")
        assert signed_in["meta"]["serial_number"] == "SN-0001" and signed_in["meta"]["part_number"] == "PN-77"
        [event] = await _audit(admin, "component_meta_changed")
        assert event["entity_id"] == "04:ATRH" and event["after"]["model"] == "HMP155"
        assert event["before"]["model"] is None

        # An old calibration with a 12-month interval: overdue, and a minor Problems item for everyone.
        old_day = today - timedelta(days=400)
        draft = {
            "component_id": atrh["id"],
            "date": old_day.isoformat(),
            "performed_by": "Calibration lab",
            "certificate": "CAL/1",
            "next_due": None,
            "interval_months": 12,
            "notes": None,
        }
        old = await admin.send("POST", "/api/v1/admin/calibrations", draft)
        assert old.status_code == 201, old.text
        assert old.json()["created_by"] == recorder and old.json()["interval_months"] == 12
        due = date.fromisoformat(old.json()["next_due"])
        assert (due.year - old_day.year) * 12 + due.month - old_day.month == 12 and due < today
        status = (await _ids(admin))["04:ATRH"]["calibration"]
        assert status == {
            "status": "overdue",
            "last": old_day.isoformat(),
            "next_due": due.isoformat(),
            "days_left": (due - today).days,
            "validated_on": None,
            "pending": True,  # no validation date: the certificate is pending
        }
        assert (await _asset(visitor, "04:ATRH"))["calibration"]["status"] == "overdue"
        assert await _overdue(visitor) == [
            {
                "code": "calibration_overdue",
                "severity": "minor",
                "link": "/systems/WIDN-CAT3/sites/04",
                "params": {
                    "site": await _site_code(visitor, "04"),
                    "component": "ATRH",
                    "due": due.isoformat(),
                },
            }
        ]

        # A new calibration today, due in 20 days: due soon within the 30-day window, and the Problems item goes.
        new = await admin.send(
            "POST",
            "/api/v1/admin/calibrations",
            {
                **draft,
                "date": today.isoformat(),
                "next_due": (today + timedelta(days=20)).isoformat(),
                "interval_months": None,
            },
        )
        assert new.status_code == 201, new.text
        assert (await _ids(admin))["04:ATRH"]["calibration"]["status"] == "due_soon"
        assert (await _asset(visitor, "04:ATRH"))["calibration"]["days_left"] == 20
        assert await _overdue(visitor) == []

        # A shorter window makes it OK; the setting takes whole days from 1 to 180 only.
        for bad in (0, 181, 1.5, "10"):
            r = await admin.send("PUT", "/api/v1/admin/settings/calibration_due_soon_days", {"value": bad})
            assert r.status_code == 422, bad
        r = await admin.send("PUT", "/api/v1/admin/settings/calibration_due_soon_days", {"value": 10})
        assert r.status_code == 200 and r.json()["calibration_due_soon_days"] == 10
        assert (await _ids(admin))["04:ATRH"]["calibration"]["status"] == "ok"
        assert (await visitor.get(f"{SYS}/assets")).json()["due_soon_days"] == 10
        r = await admin.send("PUT", "/api/v1/admin/settings/calibration_due_soon_days", {"value": 30})
        assert r.status_code == 200

        # Correcting the new record moves the status; the audit keeps what it was.
        fixed = await admin.send(
            "PATCH",
            f"/api/v1/admin/calibrations/{new.json()['id']}",
            {
                **draft,
                "date": today.isoformat(),
                "next_due": (today + timedelta(days=5)).isoformat(),
                "interval_months": None,
            },
        )
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["updated_by"] == recorder
        assert (await _ids(admin))["04:ATRH"]["calibration"]["days_left"] == 5
        [changed] = await _audit(admin, "calibration_changed")
        assert changed["entity_id"] == str(new.json()["id"])
        assert changed["after"] == {"next_due": (today + timedelta(days=5)).isoformat()}

        # Validating its certificate clears "pending" everywhere; the validation cannot come before the calibration.
        corrected = {
            **draft,
            "date": today.isoformat(),
            "next_due": (today + timedelta(days=5)).isoformat(),
            "interval_months": None,
        }
        assert (await _ids(admin))["04:ATRH"]["calibration"]["pending"] is True
        r = await admin.send(
            "PATCH",
            f"/api/v1/admin/calibrations/{new.json()['id']}",
            {**corrected, "validated_on": (today - timedelta(days=1)).isoformat()},
        )
        assert (r.status_code, r.json()["code"]) == (422, "validated_before_date")
        r = await admin.send(
            "PATCH",
            f"/api/v1/admin/calibrations/{new.json()['id']}",
            {**corrected, "validated_on": today.isoformat()},
        )
        assert r.status_code == 200 and r.json()["validated_on"] == today.isoformat()
        assert (await _ids(admin))["04:ATRH"]["calibration"]["pending"] is False
        assert (await _asset(visitor, "04:ATRH"))["calibration"]["validated_on"] == today.isoformat()

        history = (await admin.get(f"/api/v1/admin/components/{atrh['id']}/calibrations")).json()
        assert [h["id"] for h in history] == [new.json()["id"], old.json()["id"]]  # newest first

        # Removing the new record falls back to the old one (overdue again). The row is kept.
        gone = await admin.send("DELETE", f"/api/v1/admin/calibrations/{new.json()['id']}")
        assert gone.status_code == 200 and gone.json() == {"removed": new.json()["id"]}
        assert (
            await admin.send("DELETE", f"/api/v1/admin/calibrations/{new.json()['id']}")
        ).status_code == 404
        assert (await _ids(admin))["04:ATRH"]["calibration"]["status"] == "overdue"
        assert [
            h["id"] for h in (await admin.get(f"/api/v1/admin/components/{atrh['id']}/calibrations")).json()
        ] == [old.json()["id"]]
        async with engine.connect() as conn:
            kept = (
                await conn.execute(
                    text("SELECT removed_by, removed_at IS NOT NULL FROM calibration_record WHERE id = :id"),
                    {"id": new.json()["id"]},
                )
            ).one()
        assert tuple(kept) == (recorder, True)
        assert len(await _audit(admin, "calibration_added")) == 2
        assert len(await _audit(admin, "calibration_removed")) == 1

        # Refusals, with the codes the screens show.
        refusals = [
            ({**draft, "date": (today + timedelta(days=1)).isoformat()}, 422, "date_in_future"),
            ({**draft, "performed_by": "  "}, 422, "performed_by_required"),
            ({**draft, "interval_months": 121}, 422, "invalid_interval"),
            (
                {**draft, "interval_months": None, "next_due": old_day.isoformat()},
                422,
                "next_due_before_date",
            ),
            ({**draft, "interval_months": None}, 422, "next_due_required"),
            ({**draft, "component_id": dcp["id"]}, 422, "dcp_not_calibrated"),
            ({**draft, "component_id": 999999}, 404, "component_not_found"),
        ]
        for body, code, problem in refusals:
            r = await admin.send("POST", "/api/v1/admin/calibrations", body)
            assert (r.status_code, r.json().get("code")) == (code, problem), body
        r = await admin.send(
            "PATCH",
            f"/api/v1/admin/calibrations/{old.json()['id']}",
            {**draft, "component_id": rows["04:BARO"]["id"]},
        )
        assert (r.status_code, r.json()["code"]) == (422, "component_mismatch")
        r = await admin.send(
            "PUT",
            f"/api/v1/admin/components/{atrh['id']}/meta",
            {**meta, "installed_on": (today + timedelta(days=1)).isoformat()},
        )
        assert (r.status_code, r.json()["code"]) == (422, "date_in_future")
        assert len(await _audit(admin, "calibration_added")) == 2  # nothing refused was written

        # Put everything back.
        assert (
            await admin.send("DELETE", f"/api/v1/admin/calibrations/{old.json()['id']}")
        ).status_code == 200
        assert (
            await admin.send("PUT", f"/api/v1/admin/components/{atrh['id']}/meta", EMPTY_META)
        ).status_code == 200
        assert (await _ids(admin))["04:ATRH"]["calibration"]["status"] == "unknown"


async def _site_code(b: Browser, slug: str) -> str:
    """A site's code, as the Problems panel names it (the registry's code, not the slug)."""
    sites = (await b.get(SYS)).json()["sites"]
    return str(next(s["code"] for s in sites if s["slug"] == slug))


async def test_station_and_site_records(engine: AsyncEngine, recorder: str) -> None:
    async with Browser() as admin, Browser() as visitor:
        assert (await admin.login(recorder)).status_code == 200
        before = (await admin.get("/api/v1/admin/station")).json()
        station = {
            "icao": before["icao"],  # sent by the screen; not editable here
            "wmo_number": "12345",
            "airport_name": "Test airport",
            "lat": -1.5,
            "lon": 100.25,
            "elevation_m": 8.0,
            "procurement_year": 2019,
            "notes": None,
        }
        r = await admin.send("PUT", "/api/v1/admin/station", station)
        assert r.status_code == 200, r.text
        assert r.json()["wmo_number"] == "12345" and r.json()["icao"] == before["icao"]
        public = (await visitor.get(f"{SYS}/assets")).json()
        assert public["station"]["airport_name"] == "Test airport" and public["station"]["lat"] == -1.5
        [event] = await _audit(admin, "station_changed")
        assert event["entity_id"] == "WIDN-CAT3" and event["after"]["wmo_number"] == "12345"

        site = {
            "lat": -1.51,
            "lon": 100.26,
            "elevation_m": 7.5,
            "threshold_elevation_m": 7.0,
            "description": "Touchdown",
        }
        r = await admin.send("PUT", "/api/v1/admin/sites/04", site)
        assert r.status_code == 200 and r.json() == site
        assert (
            next(s for s in (await visitor.get(f"{SYS}/assets")).json()["sites"] if s["slug"] == "04")["meta"]
            == site
        )
        assert [e["entity_id"] for e in await _audit(admin, "site_changed")] == ["04"]

        for body, problem in (
            ({**station, "lat": 91}, "invalid_lat"),
            ({**station, "lon": -181}, "invalid_lon"),
            ({**station, "procurement_year": _today().year + 1}, "year_in_future"),
            ({**station, "wmo_number": "1234"}, "invalid_wmo"),
        ):
            r = await admin.send("PUT", "/api/v1/admin/station", body)
            assert (r.status_code, r.json()["code"]) == (422, problem)
        assert (
            await admin.send("PUT", "/api/v1/admin/station", {})
        ).status_code == 422  # a PUT sends everything
        assert (await admin.send("PUT", "/api/v1/admin/sites/nope", site)).status_code == 404
        assert len(await _audit(admin, "station_changed")) == 1  # refusals write nothing

        # Put everything back.
        blank_site = dict.fromkeys(site)
        assert (await admin.send("PUT", "/api/v1/admin/sites/04", blank_site)).status_code == 200
        r = await admin.send("PUT", "/api/v1/admin/station", {k: before.get(k) for k in station})
        assert r.status_code == 200


async def test_the_trace_lists_a_flag_on_the_component(engine: AsyncEngine, recorder: str) -> None:
    """FR-AUD-003: a flag on runway 04's ATRH (and its recompute) shows in that component's trace, not another's."""
    start = datetime(2026, 11, 3, 1, 0, tzinfo=UTC)
    period = {"from": "2026-11-03T00:00:00Z", "to": "2026-11-04T00:00:00Z"}
    async with Browser() as admin, Browser() as viewer, Browser() as visitor:
        assert (await admin.login(recorder)).status_code == 200
        assert (await viewer.login("rec-viewer")).status_code == 200
        atrh = (await _ids(admin))["04:ATRH"]["id"]
        created = await admin.send(
            "POST",
            "/api/v1/admin/flags",
            {
                "component_ids": [atrh],
                "start": start.isoformat(),
                "end": (start + timedelta(hours=1)).isoformat(),
                "reason": "maintenance",
                "note": "Trace test: sensor swapped.",
            },
        )
        assert created.status_code == 201, created.text
        flag, job = created.json()["flag"], created.json()["job"]
        assert (await admin.send("DELETE", f"/api/v1/admin/flags/{flag['id']}")).status_code == 200

        params = {**period, "scope": "component:04:ATRH"}
        assert (await visitor.get(f"{SYS}/trace", params=params)).status_code == 401
        trace = await viewer.get(f"{SYS}/trace", params=params)
        assert trace.status_code == 200, trace.text
        mine = [e for e in trace.json() if e["entity_type"] == "flag" and e["entity_id"] == str(flag["id"])]
        assert [e["action"] for e in mine] == ["flag_removed", "flag_created"]  # newest first
        assert mine[0]["actor"] == recorder and mine[0]["detail"]["reason"] == "maintenance"
        assert any(e["action"] == "job_started" and e["detail"]["job"] == job["id"] for e in trace.json())
        times = [e["time"] for e in trace.json()]
        assert times == sorted(times, reverse=True)

        other = (await viewer.get(f"{SYS}/trace", params={**period, "scope": "component:22:ATRH"})).json()
        assert not any(e["entity_type"] == "flag" and e["entity_id"] == str(flag["id"]) for e in other)
        later = (
            await viewer.get(
                f"{SYS}/trace",
                params={
                    "from": "2026-11-04T00:00:00Z",
                    "to": "2026-11-05T00:00:00Z",
                    "scope": "component:04:ATRH",
                },
            )
        ).json()
        assert not any(
            e["entity_type"] == "flag" and e["entity_id"] == str(flag["id"]) for e in later
        )  # the flag was on another day
        assert (
            await viewer.get(f"{SYS}/trace", params={**period, "scope": "component:04:NOPE"})
        ).status_code == 404


IMPORT = {
    "components": [
        {"site": "04", "type": "ATRH", "installed_on": "2025-12-23"},
        {"site": "04", "type": "DCP", "installed_on": "2025-12-23"},
    ],
    "calibrations": [
        {
            "site": "04",
            "type": "ATRH",
            "date": "2025-12-27",
            "performed_by": "BMKG",
            "interval_months": 12,
            "validated_on": "2025-12-31",
            "notes": "Calibration work 27-28 Dec 2025.",
        },
        {"site": "04", "type": "BARO", "date": "2025-12-27", "performed_by": "BMKG", "interval_months": 12},
    ],
}


def _args(path: Path, *, dry_run: bool) -> argparse.Namespace:
    return argparse.Namespace(file=str(path), actor="records-import", system="WIDN-CAT3", dry_run=dry_run)


async def test_the_import_is_checked_audited_and_repeatable(
    engine: AsyncEngine, recorder: str, tmp_path: Path
) -> None:
    """R2.5.1: `simola import-records` writes like the Admin screens, adds nothing the second time, and writes
    nothing when any entry is refused."""
    today = _today()
    path = tmp_path / "records.json"
    path.write_text(json.dumps(IMPORT))
    async with Browser() as admin:
        assert (await admin.login(recorder)).status_code == 200

        assert await _cmd_import_records(_args(path, dry_run=True)) == 0
        rows = await _ids(admin)
        assert rows["04:ATRH"]["meta"]["installed_on"] is None  # a dry run writes nothing
        assert rows["04:BARO"]["calibration"]["status"] == "unknown"

        assert await _cmd_import_records(_args(path, dry_run=False)) == 0
        rows = await _ids(admin)
        assert (
            rows["04:ATRH"]["meta"]["installed_on"] == rows["04:DCP"]["meta"]["installed_on"] == "2025-12-23"
        )
        assert rows["04:ATRH"]["calibration"] | {"status": None, "days_left": None} == {
            "status": None,
            "last": "2025-12-27",
            "next_due": "2026-12-27",
            "days_left": None,
            "validated_on": "2025-12-31",
            "pending": False,
        }
        assert rows["04:BARO"]["calibration"]["pending"] is True  # no validation date given
        added = [e for e in await _audit(admin, "calibration_added") if e["actor"] == "records-import"]
        assert len(added) == 2 and {e["after"]["component"] for e in added} == {"04:ATRH", "04:BARO"}
        changed = [e for e in await _audit(admin, "component_meta_changed") if e["actor"] == "records-import"]
        assert sorted(e["entity_id"] for e in changed) == ["04:ATRH", "04:DCP"]

        # The same file again changes nothing.
        async with engine.begin() as conn:
            system = await load_system(conn, "WIDN-CAT3")
            assert system is not None
            again = await run_import(
                conn, system, ImportDoc.model_validate(IMPORT), actor="records-import", today=today
            )
        assert again == {
            "components_changed": 0,
            "components_unchanged": 2,
            "calibrations_added": 0,
            "calibrations_skipped": 2,
        }

        # One refused entry stops the whole import: nothing is written, every problem is listed.
        good = {
            "site": "04",
            "type": "RVR",
            "date": "2025-12-27",
            "performed_by": "BMKG",
            "interval_months": 12,
        }
        bad = {
            "components": [
                {"site": "04", "type": "BARO", "installed_on": (today + timedelta(days=1)).isoformat()}
            ],
            "calibrations": [
                good,
                {**good, "type": "DCP"},
                {**good, "type": "NOPE"},
                {**good, "type": "CEL", "validated_on": "2025-12-20"},
            ],
        }
        with pytest.raises(ImportRefused) as refused:
            async with engine.begin() as conn:
                assert system is not None
                await run_import(
                    conn, system, ImportDoc.model_validate(bad), actor="records-import", today=today
                )
        assert refused.value.problems == [
            "components 04:BARO: date_in_future",
            "calibrations 04:DCP 2025-12-27: dcp_not_calibrated",
            "calibrations 04:NOPE 2025-12-27: unknown component",
            "calibrations 04:CEL 2025-12-27: validated_before_date",
        ]
        assert (await _ids(admin))["04:RVR"]["calibration"]["status"] == "unknown"

        # Put everything back.
        for key in ("04:ATRH", "04:BARO"):
            for cal in (await admin.get(f"/api/v1/admin/components/{rows[key]['id']}/calibrations")).json():
                assert (
                    await admin.send("DELETE", f"/api/v1/admin/calibrations/{cal['id']}")
                ).status_code == 200
        for key in ("04:ATRH", "04:DCP"):
            r = await admin.send("PUT", f"/api/v1/admin/components/{rows[key]['id']}/meta", EMPTY_META)
            assert r.status_code == 200
