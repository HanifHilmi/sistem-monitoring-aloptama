"""CSV export layout (R3.4, FR-EXP-002): cells, file names, rows. The database side is in
tests/integration/test_exports.py."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from typing import Any

from simola import exports
from simola.kpi.engine import Counts
from simola.registry import Cdp, Component, MetricField, Site, System

GEN = datetime(2026, 11, 8, 5, 30, 12, tzinfo=UTC)


def _system() -> System:
    spec = [
        ("TEMP", "temp_c", "numeric", "°C"),
        ("RH", "rh_pct", "numeric", "%"),
        ("RVR", "rvr_m", "numeric", "m"),
        ("D/N", "als_dn", "text", None),
    ]
    fields = {c: MetricField(c, col, vt, u, c, c, i) for i, (c, col, vt, u) in enumerate(spec)}

    def comp(cid: int, type_code: str, flds: tuple[str, ...], mand: tuple[str, ...]) -> Component:
        return Component(
            cid, 1, type_code, type_code == "DCP", type_code, type_code, cid, flds, mand, None, None
        )

    site = Site(
        1,
        "RWY04",
        "04",
        "04",
        "Runway 04",
        "Runway 04",
        1,
        (
            comp(1, "DCP", (), ()),
            comp(2, "ATRH", ("TEMP", "RH"), ("TEMP", "RH")),
            comp(3, "RVR", ("RVR", "D/N"), ("RVR",)),
        ),
    )
    return System(
        1,
        "WIDN-CAT3",
        "AWOS_CAT3",
        "sla_ola",
        "x",
        "x",
        "WIDN",
        datetime(2025, 12, 24, 3, 40, tzinfo=UTC),
        (Cdp(1, "CDP1", 1), Cdp(2, "CDP2", 2)),
        (site,),
        fields,
    )


def _read(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_text_that_looks_like_a_formula_is_made_safe_numbers_are_not() -> None:
    assert exports.text_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert exports.text_cell("@SUM") == "'@SUM"
    assert exports.text_cell("-RA") == "'-RA"  # present weather: light rain
    assert exports.text_cell(None) == ""
    assert exports.number_cell(-1.5) == "-1.5"  # a number stays a number
    assert exports.number_cell(1013.0) == "1013"
    assert exports.number_cell(23.4) == "23.4"
    assert exports.number_cell(float("nan")) == ""
    assert exports.number_cell(None) == ""
    assert exports.number_cell(True) == "true"
    assert exports.pct_cell(1432, 1440) == "99.44"
    assert exports.pct_cell(0, 0) == ""
    assert exports.pct_cell(1, 3) == "33.33"


def test_file_names_match_the_exports_page() -> None:
    # the same cases as frontend/src/utils/exports.test.ts
    nov = (datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))
    assert exports.file_name("WIDN-CAT3", "daily", *nov) == "SIMOLA_WIDN-CAT3_daily_2026-11-01_2026-11-30.csv"
    assert (
        exports.file_name("WIDN-CAT3", "minutes", *nov, "RWY04")
        == "SIMOLA_WIDN-CAT3_minutes_RWY04_2026-11-01_2026-11-30.csv"
    )
    a, b = datetime(2026, 11, 3, 10, 30, tzinfo=UTC), datetime(2026, 11, 3, 12, tzinfo=UTC)
    assert (
        exports.file_name("WIDN-CAT3", "alarms", a, b)
        == "SIMOLA_WIDN-CAT3_alarms_2026-11-03T1030Z_2026-11-03T1200Z.csv"
    )


def test_a_day_gives_the_system_its_cdps_each_site_and_each_sensor() -> None:
    sy = _system()
    c = Counts()
    c.add(("sla", 1), 1430, 1440)
    c.add(("cdp_flow", 1), 1400, 1440)
    c.add(("cdp_reach", 1), 1380, 1390)
    c.add(("cdp_flow", 2), 1420, 1440)
    c.add(("component", 1), 1440, 1440)
    c.add(("component", 2), 1432, 1440)
    c.add(("component", 3), 0, 0)  # out of service all day
    rows = list(exports.daily_rows(sy, date(2026, 11, 1), c, exports.Stamp(GEN)))
    assert [r[1] for r in rows] == ["system", "cdp", "cdp", "site", "component", "component", "component"]
    assert all(len(r) == len(exports.DAILY_HEADER) for r in rows)
    system, cdp1, cdp2, site, dcp, atrh, rvr = rows
    assert dcp[4] == "DCP"
    assert system[:9] == ["2026-11-01", "system", "", "", "", "1440", "1430", "10", "99.31"]
    assert cdp1[2] == "CDP1" and cdp1[5:11] == ["1440", "1400", "40", "97.22", "1380", "1390"]
    assert cdp2[9:11] == ["0", "0"]  # no probe that day
    # a site: its sensors' minutes added up
    assert site[3] == "RWY04" and site[5:9] == ["2880", "2872", "8", "99.72"]
    assert atrh[3:9] == ["RWY04", "ATRH", "1440", "1432", "8", "99.44"]
    assert rvr[5:9] == ["0", "0", "0", ""]
    assert system[-2:] == ["1.0", "2026-11-08T05:30:12Z"]


def test_the_minute_file_has_a_status_per_sensor_and_units_in_the_headers() -> None:
    sy = _system()
    site = sy.sites[0]
    header = exports.minute_header(sy, site)
    assert header == [
        "time_utc",
        "cdps",
        "DCP.status",
        "ATRH.status",
        "ATRH.TEMP (°C)",
        "ATRH.RH (%)",
        "RVR.status",
        "RVR.RVR (m)",
        "RVR.D/N",
        "definitions_version",
        "generated_at_utc",
    ]
    a = datetime(2026, 11, 1, tzinfo=UTC)
    m1 = a + timedelta(minutes=1)
    records: dict[datetime, dict[str, Any]] = {
        a: {"temp_c": 27.0, "rh_pct": 81.5, "rvr_m": 2000.0, "als_dn": "D"},
        m1: {"temp_c": 27.1, "rh_pct": None},
    }
    rows = list(
        exports.minute_rows(
            sy,
            site,
            a,
            3,
            {1: "vvn", 2: "vfn", 3: "gun"},
            records,
            {a: [2, 1], m1: [1]},
            exports.Stamp(GEN),
        )
    )
    assert rows[0] == [
        "2026-11-01T00:00:00Z",
        "CDP1 CDP2",
        "valid",
        "valid",
        "27",
        "81.5",
        "flagged",
        "2000",
        "D",
        "1.0",
        "2026-11-08T05:30:12Z",
    ]
    assert rows[1][:9] == [
        "2026-11-01T00:01:00Z",
        "CDP1",
        "valid",
        "field_missing",
        "27.1",
        "",
        "not_counted",
        "",
        "",
    ]
    assert rows[2][:9] == ["2026-11-01T00:02:00Z", "", "no_data", "no_data", "", "", "no_data", "", ""]
    assert all(len(r) == len(header) for r in rows)


def test_a_file_starts_with_the_byte_order_mark_and_its_header() -> None:
    lines = exports.Lines()
    text = exports.BOM + lines([exports.ALARM_HEADER]) + lines([["2026-11-03T10:43:12Z", "a,b", "error"]])
    assert text.startswith("\ufefftime_utc,alarm_name,")
    assert text.endswith('"a,b",error\r\n')  # commas inside a cell are quoted
    assert _read(text.removeprefix(exports.BOM))[0] == exports.ALARM_HEADER


def test_alarm_rows_say_what_each_change_did() -> None:
    sy = _system()
    e = {
        "time": datetime(2026, 11, 3, 10, 43, 12, tzinfo=UTC),
        "name": "DCPA_Missing",
        "type": "error",
        "state": "pending",
        "active": True,
        "raised": True,
        "message": "=cmd",
        "cdp_ids": [1, 2],
        "place_kind": "component",
        "site_id": 1,
        "component_type": "DCP",
    }
    row = exports.alarm_row(sy, e, exports.Stamp(GEN))
    assert row[:10] == [
        "2026-11-03T10:43:12Z",
        "DCPA_Missing",
        "error",
        "raised",
        "pending",
        "component",
        "RWY04",
        "DCP",
        "'=cmd",
        "CDP1 CDP2",
    ]
    assert len(row) == len(exports.ALARM_HEADER)
    assert exports.change_word(True, False) == "acknowledged"
    assert exports.change_word(False, False) == "cleared"
    station = exports.alarm_row(
        sy, {**e, "place_kind": "station", "site_id": None, "component_type": None}, exports.Stamp(GEN)
    )
    assert station[5:8] == ["station", "", ""]


def test_limits() -> None:
    assert exports.MAX_SPAN["minutes"] == timedelta(days=31)
    assert (
        exports.MAX_SPAN["daily"]
        == exports.MAX_SPAN["alarms"]
        == exports.MAX_SPAN["quality"]
        == timedelta(days=366)
    )
    assert len(set(exports.QUALITY_HEADER)) == len(exports.QUALITY_HEADER)
    for h in (exports.DAILY_HEADER, exports.ALARM_HEADER, exports.QUALITY_HEADER):
        assert h[-2:] == exports.TRAILER
