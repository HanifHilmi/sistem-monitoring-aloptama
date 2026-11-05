"""Parser tests against real CDP files (FR-ING-002, PRD §15.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from simola.ingestion import widn
from tests.conftest import fixture_text, missing_minutes


def _parse(name: str) -> widn.ParseResult:
    return widn.parse_text(fixture_text(name))


def test_cdp1_2026_11_03_gaps_match_source() -> None:
    res = _parse("cdp1_091OneMinute.20261103.dat")
    minutes = {r.time for r in res.records}
    assert missing_minutes(minutes, "2026-11-03") == [
        "00:30",
        "10:38",
        "10:39",
        "10:40",
        "10:41",
        "10:42",
        "10:50",
        "10:51",
        "10:52",
        "13:11",
    ]


def test_cdp2_2026_11_03_gaps_match_source() -> None:
    res = _parse("cdp2_091OneMinute.20261103.dat")
    minutes = {r.time for r in res.records}
    assert missing_minutes(minutes, "2026-11-03") == [
        "00:30",
        "10:49",
        "10:50",
        "10:51",
        "10:52",
        "10:53",
        "10:54",
    ]


def test_golden_minute_matches_v2_production_values() -> None:
    """2026-10-29 12:00 from CDP2's file equals the row v2 stored for that minute (all fields, 3 sites)."""
    res = _parse("cdp2_091OneMinute.20261029.dat")
    rec = next(r for r in res.records if r.time == datetime(2026, 10, 29, 12, 0, tzinfo=UTC))
    s04, s22, smid = (rec.stations[k].values for k in ("04", "22", "M"))
    assert s04 == {
        "WS": 0.0,
        "WD": 360.0,
        "WGS": 0.0,
        "WGD": 0.0,
        "TEMP": 25.3,
        "DEWP": 25.1,
        "RH": 98.0,
        "QNH": 1013.1,
        "DA": 1700.0,
        "ALS": 5.0,
        "D/N": "N",
        "VIS": 10412.0,
        "RVR": 8149.0,
        "RLS": 1.0,
        "LR1": 168.0,
        "SKY": "BKN170 BKN310 BKN330",
        "RA": 0.0,
        "PW": "",
    }
    assert {
        k: s22[k]
        for k in ("WS", "WD", "TEMP", "DEWP", "RH", "QNH", "DA", "VIS", "RVR", "LR1", "SKY", "RA", "PW")
    } == {
        "WS": 1.0,
        "WD": 92.0,
        "TEMP": 25.3,
        "DEWP": 25.0,
        "RH": 98.0,
        "QNH": 1013.0,
        "DA": 1700.0,
        "VIS": 7832.0,
        "RVR": 5725.0,
        "LR1": 162.0,
        "SKY": "BKN160 BKN310 BKN330",
        "RA": 0.0,
        "PW": "",
    }
    assert smid == {
        "WS": 1.0,
        "WD": 132.0,
        "WGS": 0.0,
        "WGD": 0.0,
        "TEMP": 25.6,
        "DEWP": 25.1,
        "RH": 97.0,
        "QNH": 1013.1,
        "DA": 1700.0,
        "RA": 0.0,
        "SOL": 0.0,
        "LTX": "",
    }


def test_commissioning_day_starts_with_all_missing_records() -> None:
    res = _parse("cdp1_091OneMinute.20251224.dat")
    first = res.records[0]
    assert first.time == datetime(2025, 12, 24, 3, 40, tzinfo=UTC)
    assert all(st.all_missing for st in first.stations.values())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  ///", None),
        ("/", None),
        ("   M ", None),
        ("N/A", None),
        ("---", None),
        ("     ", 0.0),
        ("  12", 12.0),
        ("1,5", 1.5),
    ],
)
def test_numeric_tokens(raw: str, expected: float | None) -> None:
    value, warn = widn.parse_value(raw, widn.FieldSlice("X", 0, len(raw), 1.0))
    assert value == expected
    assert warn is False


def test_unparseable_numeric_is_missing_with_warning() -> None:
    assert widn.parse_value(" 1x2 ", widn.FieldSlice("X", 0, 5, 1.0)) == (None, True)


def test_scale_applied() -> None:
    assert widn.parse_value(" 253", widn.FieldSlice("TEMP", 0, 4, 0.1)) == (25.3, False)


@pytest.mark.parametrize(
    ("raw", "expected"), [("BKN170", "BKN170"), ("   ", ""), ("//////", None), ("M", None)]
)
def test_text_tokens(raw: str, expected: str | None) -> None:
    assert widn.parse_value(raw, widn.FieldSlice("SKY", 0, len(raw), None)) == (expected, False)


def test_gust_rule() -> None:
    v: dict[str, widn.Value] = {"WS": 3.0, "WD": 120.0, "WGS": None, "WGD": None}
    widn._apply_gust_rule(v)
    assert v["WGS"] == 0.0 and v["WGD"] == 0.0
    v = {"WS": None, "WD": 120.0, "WGS": 5.0, "WGD": 100.0}
    widn._apply_gust_rule(v)
    assert v["WGS"] is None and v["WGD"] is None


def test_duplicate_minute_later_line_wins() -> None:
    header = "h1\nh2\nh3\nh4\n"
    line = "091 20261101 10 00" + " " * 60 + "{t}" + "\n"
    content = header + line.format(t=" 250") + line.format(t=" 260")
    res = widn.parse_text(content)
    assert res.duplicate_minutes == 1
    assert len(res.records) == 1


def test_present_weather_and_lightning_are_read_in_full() -> None:
    """Present weather is 10 characters wide and the lightning text runs to the end of the line.

    v2's slices cut them to 6 and 32 characters ("VCTS DZ" -> "VCTS D"); checked against CDP files 2026-11-05.
    """
    lines = fixture_text("cdp1_091OneMinute.20261103.dat").splitlines()
    head, line = lines[: widn.HEADER_LINES], lines[widn.HEADER_LINES + 600].ljust(332)
    line = (
        line[:306]
        + "VCTS DZ".ljust(10)
        + "-TSRA".ljust(10)
        + line[326:332]
        + "TS in Vicinity - LTG DSNT S AND NW"
    )
    rec = widn.parse_text("\n".join([*head, line])).records[0]
    assert rec.stations["04"].values["PW"] == "VCTS DZ"
    assert rec.stations["22"].values["PW"] == "-TSRA"
    assert rec.stations["M"].values["LTX"] == "TS in Vicinity - LTG DSNT S AND NW"
