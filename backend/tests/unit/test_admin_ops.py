"""Settings rules, mandatory-field rules and the days an in-service change touches (R2.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from simola.api.deps import ApiError
from simola.api.routers.admin_ops import affected_days, check_mandatory, validate_setting
from simola.registry import Component, MetricField, Site, System


def _system() -> System:
    fields = {
        code: MetricField(code, code.lower(), "numeric", None, code, code, i)
        for i, code in enumerate(["TEMP", "DEWP", "RH", "RVR", "VIS", "ALS"])
    }

    def comp(cid: int, site: int, type_code: str, flds: tuple[str, ...], mand: tuple[str, ...]) -> Component:
        return Component(
            cid, site, type_code, type_code == "DCP", type_code, type_code, cid, flds, mand, None, None
        )

    sites = (
        Site(
            1,
            "RWY04",
            "04",
            "04",
            "Runway 04",
            "Runway 04",
            1,
            (
                comp(1, 1, "DCP", (), ()),
                comp(2, 1, "ATRH", ("TEMP", "DEWP", "RH"), ("TEMP", "RH")),
                comp(3, 1, "RVR", ("RVR", "VIS", "ALS"), ("RVR",)),
            ),
        ),
        Site(
            2,
            "RWY22",
            "22",
            "22",
            "Runway 22",
            "Runway 22",
            2,
            (
                comp(4, 2, "ATRH", ("TEMP", "DEWP", "RH"), ("TEMP", "RH")),
                comp(5, 2, "RVR", ("RVR", "VIS"), ("RVR",)),
            ),
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
        datetime(2025, 12, 24, tzinfo=UTC),
        (),
        sites,
        fields,
    )


def _code(exc: pytest.ExceptionInfo[ApiError]) -> str:
    return exc.value.code


def test_mandatory_fields_come_back_in_field_order() -> None:
    assert check_mandatory(_system(), "ATRH", ["RH", "DEWP", "TEMP", "RH"]) == ["TEMP", "DEWP", "RH"]


@pytest.mark.parametrize(
    ("type_code", "fields", "code"),
    [
        ("ATRH", [], "at_least_one"),
        ("ATRH", ["TEMP", "QNH"], "unknown_field"),
        ("DCP", ["TEMP"], "dcp_rule_fixed"),
        ("BARO", ["QNH"], "component_type_not_found"),
        # ALS exists only at runway 04: runway 22's RVR would be left without a mandatory field, and the
        # registry would then refuse to load.
        ("RVR", ["ALS"], "no_mandatory_at_site"),
    ],
)
def test_mandatory_fields_that_are_refused(type_code: str, fields: list[str], code: str) -> None:
    with pytest.raises(ApiError) as exc:
        check_mandatory(_system(), type_code, fields)
    assert _code(exc) == code


def test_a_field_missing_at_one_site_is_fine_while_each_site_keeps_one() -> None:
    assert check_mandatory(_system(), "RVR", ["RVR", "ALS"]) == ["RVR", "ALS"]


@pytest.mark.parametrize(
    ("key", "value", "stored"),
    [
        ("color_thresholds", {"good": 99, "warning": 95}, {"good": 99.0, "warning": 95.0}),
        ("color_thresholds", {"good": 99.5, "warning": 97}, {"good": 99.5, "warning": 97.0}),
        ("grace_minutes", 5, 5),
        (
            "problem_thresholds",
            {
                "cdp_no_data_min": 3,
                "cdp_unreachable_min": 2,
                "site_no_data_min": 2,
                "field_missing_min": 10,
                "ingest_lag_min": 5,
            },
            {
                "cdp_no_data_min": 3,
                "cdp_unreachable_min": 2,
                "site_no_data_min": 2,
                "field_missing_min": 10,
                "ingest_lag_min": 5,
            },
        ),
    ],
)
def test_valid_settings(key: str, value: object, stored: object) -> None:
    assert validate_setting(key, value) == stored


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("color_thresholds", {"good": 95, "warning": 99}),
        ("color_thresholds", {"good": 101, "warning": 95}),
        ("color_thresholds", {"good": 99}),
        ("grace_minutes", 0),
        ("grace_minutes", 16),
        ("grace_minutes", "3"),
        ("grace_minutes", 2.5),
        ("problem_thresholds", {"cdp_no_data_min": 0}),
        (
            "problem_thresholds",
            {
                "cdp_no_data_min": 500,
                "cdp_unreachable_min": 2,
                "site_no_data_min": 2,
                "field_missing_min": 5,
                "ingest_lag_min": 5,
            },
        ),
    ],
)
def test_invalid_settings(key: str, value: object) -> None:
    with pytest.raises(ApiError) as exc:
        validate_setting(key, value)
    assert _code(exc) == "invalid_setting"


def test_unknown_setting() -> None:
    with pytest.raises(ApiError) as exc:
        validate_setting("backup_expected", True)
    assert exc.value.status_code == 404


COVERAGE, TODAY = date(2025, 12, 24), date(2026, 11, 5)


def _t(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T00:00:00+00:00")


@pytest.mark.parametrize(
    ("old", "new", "days"),
    [
        ((None, None), (None, None), None),
        # installed later than data began: every day up to installation changes
        ((None, None), (_t("2026-01-15"), None), (COVERAGE, date(2026, 1, 15))),
        # removed: every day from removal to today changes
        ((None, None), (None, _t("2026-10-01")), (date(2026, 10, 1), TODAY)),
        # moved later by two weeks
        ((_t("2026-01-15"), None), (_t("2026-01-29"), None), (date(2026, 1, 15), date(2026, 1, 29))),
        # both ends move: one range covering both
        (
            (_t("2026-02-01"), _t("2026-03-01")),
            (_t("2026-02-10"), _t("2026-04-01")),
            (date(2026, 2, 1), date(2026, 4, 1)),
        ),
        # a removal planned for the future touches no stored day
        ((None, None), (None, _t("2026-12-31")), None),
    ],
)
def test_days_an_in_service_change_touches(
    old: tuple[datetime | None, datetime | None],
    new: tuple[datetime | None, datetime | None],
    days: tuple[date, date] | None,
) -> None:
    assert affected_days(old, new, COVERAGE, TODAY) == days
