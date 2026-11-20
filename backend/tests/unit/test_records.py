"""Records, parts and calibration rules (R2.5, R3.7, FR-REG-004/005, PRD §9.5)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from simola.records import (
    RecordError,
    add_months,
    calibration_status,
    check_calibration,
    check_installed,
    check_place,
    check_removal,
    check_replacement,
    public_part,
    same_part_name,
)
from simola.records_import import ImportDoc

TODAY = date(2026, 11, 5)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap year
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),
        (date(2026, 3, 31), 12, date(2027, 3, 31)),
        (date(2026, 5, 10), 120, date(2036, 5, 10)),
    ],
)
def test_add_months_keeps_the_day_or_takes_the_last_one(start: date, months: int, expected: date) -> None:
    assert add_months(start, months) == expected


@given(st.dates(min_value=date(1950, 1, 1), max_value=date(2100, 1, 1)), st.integers(1, 120))
def test_add_months_lands_in_the_right_month_and_never_rolls_over(start: date, months: int) -> None:
    out = add_months(start, months)
    assert (out.year - start.year) * 12 + out.month - start.month == months
    assert out.day <= start.day
    assert out > start


def test_status_follows_the_due_date_and_window() -> None:
    last = date(2025, 11, 1)

    def status(due: date, window: int = 30) -> str:
        return str(calibration_status(due, last, TODAY, window)["status"])

    assert calibration_status(None, None, TODAY, 30) == {
        "status": "unknown",
        "last": None,
        "next_due": None,
        "days_left": None,
        "validated_on": None,
        "pending": False,
    }
    assert status(TODAY - timedelta(days=1)) == "overdue"  # overdue starts the day after the due date
    assert status(TODAY) == "due_soon"
    assert status(TODAY + timedelta(days=30)) == "due_soon"
    assert status(TODAY + timedelta(days=31)) == "ok"
    assert status(TODAY + timedelta(days=31), window=60) == "due_soon"
    out = calibration_status(TODAY - timedelta(days=4), last, TODAY, 30)
    assert out == {
        "status": "overdue",
        "last": last,
        "next_due": TODAY - timedelta(days=4),
        "days_left": -4,
        "validated_on": None,
        "pending": True,  # done, certificate not validated yet
    }
    validated = calibration_status(TODAY + timedelta(days=90), last, TODAY, 30, last + timedelta(days=4))
    assert validated["status"] == "ok" and validated["pending"] is False


def _code(fn: Callable[..., object], *args: object) -> str | None:
    try:
        fn(*args)
    except RecordError as exc:
        return exc.code
    return None


def test_calibration_checks_as_the_prd_says() -> None:
    d = date(2026, 10, 1)
    assert check_calibration(d, "Lab", date(2027, 10, 1), None, TODAY) == date(2027, 10, 1)
    assert check_calibration(d, "Lab", None, 12, TODAY) == date(2027, 10, 1)
    assert check_calibration(d, "Lab", date(2030, 1, 1), 6, TODAY) == date(2027, 4, 1)  # the interval wins
    assert check_calibration(TODAY, "Lab", None, 1, TODAY) == date(2026, 12, 5)  # today is allowed
    assert _code(check_calibration, TODAY + timedelta(days=1), "Lab", None, 12, TODAY) == "date_in_future"
    assert _code(check_calibration, d, "  ", None, 12, TODAY) == "performed_by_required"
    assert _code(check_calibration, d, "Lab", None, 0, TODAY) == "invalid_interval"
    assert _code(check_calibration, d, "Lab", None, 121, TODAY) == "invalid_interval"
    assert _code(check_calibration, d, "Lab", None, None, TODAY) == "next_due_required"
    assert _code(check_calibration, d, "Lab", d, None, TODAY) == "next_due_before_date"
    # the certificate's validation date: optional, not before the calibration, not in the future
    assert check_calibration(d, "Lab", None, 12, TODAY, date(2026, 10, 4)) == date(2027, 10, 1)
    assert check_calibration(d, "Lab", None, 12, TODAY, d) == date(2027, 10, 1)  # validated the same day
    assert _code(check_calibration, d, "Lab", None, 12, TODAY, date(2026, 9, 30)) == "validated_before_date"
    assert _code(check_calibration, d, "Lab", None, 12, TODAY, TODAY + timedelta(days=1)) == "date_in_future"
    assert _code(check_installed, TODAY + timedelta(days=1), TODAY) == "date_in_future"
    assert _code(check_installed, TODAY, TODAY) is None and _code(check_installed, None, TODAY) is None


def test_place_checks() -> None:
    ok = {"lat": -1.5, "lon": 100.25, "procurement_year": 2019, "wmo_number": "12345"}
    assert _code(check_place, ok, TODAY) is None
    assert _code(check_place, {"lat": None, "lon": None}, TODAY) is None
    assert _code(check_place, {"lat": 90.5}, TODAY) == "invalid_lat"
    assert _code(check_place, {"lon": -180.1}, TODAY) == "invalid_lon"
    assert _code(check_place, {"procurement_year": 2027}, TODAY) == "year_in_future"
    assert _code(check_place, {"procurement_year": 1949}, TODAY) == "year_in_future"
    assert _code(check_place, {"wmo_number": "9674"}, TODAY) == "invalid_wmo"
    assert _code(check_place, {"wmo_number": "9674a"}, TODAY) == "invalid_wmo"


def test_serial_and_part_numbers_are_for_signed_in_users() -> None:
    part = {
        "role": "Ceilometer",
        "model": "CL51",
        "serial_number": "S123",
        "part_number": "P9",
        "firmware": "2.1",
        "notes": "spare in the store",
        "removed_reason": None,
        "created_by": "andi",
        "created_at": None,
        "updated_by": None,
        "updated_at": None,
    }
    assert public_part(part, full=True) == part
    assert public_part(part, full=False) == {"role": "Ceilometer", "model": "CL51", "firmware": "2.1"}


def test_a_part_comes_out_once_and_not_before_it_went_in() -> None:
    part = {"installed_on": date(2025, 12, 24), "removed_on": None}
    assert _code(check_removal, part, date(2026, 10, 14), TODAY) is None
    assert _code(check_removal, part, date(2025, 12, 24), TODAY) is None  # the same day
    assert _code(check_removal, part, date(2025, 12, 23), TODAY) == "removed_before_installed"
    assert _code(check_removal, part, TODAY + timedelta(days=1), TODAY) == "date_in_future"
    assert (
        _code(check_removal, {**part, "removed_on": date(2026, 1, 1)}, TODAY, TODAY) == "part_already_removed"
    )
    assert _code(check_removal, {**part, "installed_on": None}, date(2001, 1, 1), TODAY) is None
    # the new part goes in on or after the day the old one came out
    assert _code(check_replacement, date(2026, 10, 14), date(2026, 10, 14)) is None
    assert _code(check_replacement, date(2026, 10, 14), None) is None
    assert _code(check_replacement, date(2026, 10, 14), date(2026, 10, 13)) == "installed_before_removed"


def test_part_names_match_without_case_or_extra_spaces() -> None:
    assert same_part_name("Receiver  1", " receiver 1")
    assert not same_part_name("Receiver 1", "Receiver 2")


def test_an_import_file_names_only_known_fields_and_blank_means_empty() -> None:
    doc = ImportDoc.model_validate_json(
        """{"components": [{"site": "04", "type": "ATRH", "installed_on": "2025-12-23", "notes": "  "}],
            "calibrations": [{"site": "04", "type": "ATRH", "date": "2025-12-27", "performed_by": " BMKG ",
                              "interval_months": 12, "validated_on": "2025-12-31"}]}"""
    )
    [c] = doc.components
    assert c.model_fields_set == {"site", "type", "installed_on", "notes"} and c.notes is None
    assert doc.calibrations[0].performed_by == "BMKG" and doc.calibrations[0].validated_on == date(
        2025, 12, 31
    )
    # R3.7: parts per sensor, and the older form whose model and numbers go to the main part
    doc = ImportDoc.model_validate_json(
        """{"components": [{"site": "04", "type": "CEL", "parts": [{"role": " Blower ", "serial_number": "B1"}]},
                           {"site": "04", "type": "DCP", "model": "1192-240"}],
            "calibrations": [{"site": "04", "type": "CEL", "date": "2025-12-27", "performed_by": "BMKG",
                              "interval_months": 12, "part": "Ceilometer"}]}"""
    )
    assert doc.components[0].parts[0].role == "Blower" and doc.components[1].model == "1192-240"
    assert doc.calibrations[0].part == "Ceilometer"
    for bad in (
        '{"component": []}',  # a typo is refused, not ignored
        '{"components": [{"site": "04", "type": "CEL", "parts": [{"serial_number": "x"}]}]}',  # no part name
        '{"components": [{"site": "04", "type": "CEL", "parts": [{"role": "Blower", "serial": "x"}]}]}',
        '{"components": [{"site": "04", "type": "ATRH", "serial": "x"}]}',
        '{"calibrations": [{"site": "04", "type": "ATRH"}]}',  # no date
    ):
        with pytest.raises(ValueError):
            ImportDoc.model_validate_json(bad)
