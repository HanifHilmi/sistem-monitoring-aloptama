"""Manual flags (R2.3): the rules a flag must meet, the days it recalculates, and how flagged minutes are counted
in the validity clause, the minute view and the outage breakdown (pure functions).

The SQL side (the flag tables, the recompute, U4's "60 minutes flagged = 60 minutes lost") is covered by
tests/integration/test_flags.py in CI.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from simola.api.deps import ApiError
from simola.api.routers.flags import FlagBody, check_flag, flag_days, union_days
from simola.kpi.engine import Invalid, component_condition
from simola.kpi.minutes import apply_invalid, intervals
from simola.kpi.outages import Outage, flagged_outages
from tests.unit.test_matrix_minutes import _system

T0 = datetime(2026, 11, 3, tzinfo=UTC)
NOW = datetime(2026, 11, 5, 12, 30, 20, tzinfo=UTC)


def m(i: int) -> datetime:
    return T0 + timedelta(minutes=i)


def flag(fid: int, a: int, b: int, reason: str = "sensor_fault") -> Invalid:
    return Invalid(m(a), m(b), "flag", fid, reason)


def body(**kw: Any) -> FlagBody:
    base: dict[str, Any] = {
        "component_ids": [11],
        "start": "2026-11-03T10:00:30Z",
        "end": "2026-11-03T11:00:59Z",
        "reason": "maintenance",
        "note": "  Cable replaced.  ",
    }
    return FlagBody.model_validate(base | kw)


# ---------------------------------------------------------------------------- rules
def test_a_valid_flag_is_cut_to_whole_minutes_and_its_note_trimmed() -> None:
    d = check_flag(_system(), body(), NOW)
    assert (d.start, d.end) == (m(600), m(660))
    assert [c.type_code for c in d.components] == ["ATRH"]
    assert (d.reason, d.note) == ("maintenance", "Cable replaced.")


def test_a_flag_may_end_in_the_current_minute() -> None:
    assert check_flag(_system(), body(end="2026-11-05T12:31:00Z"), NOW).end == datetime(
        2026, 11, 5, 12, 31, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"component_ids": []}, "no_components"),
        ({"component_ids": [99]}, "component_not_found"),
        ({"component_ids": [11, 10]}, "dcp_cannot_be_flagged"),
        ({"start": "2026-11-03T10:00:00"}, "invalid_time"),
        ({"end": "2026-11-03T10:00:40Z"}, "invalid_period"),  # same minute as the start
        ({"end": "2026-11-05T12:32:00Z"}, "flag_in_future"),
        ({"start": "2025-12-23T23:00:00Z"}, "before_coverage"),
        ({"reason": "bird"}, "invalid_reason"),
        ({"note": "  ok "}, "note_required"),
        ({"note": "x" * 501}, "note_too_long"),
    ],
)
def test_flags_that_are_refused(change: dict[str, Any], code: str) -> None:
    with pytest.raises(ApiError) as exc:
        check_flag(_system(), body(**change), NOW)
    assert exc.value.code == code and exc.value.status_code == 422


COVERAGE, TODAY = date(2025, 12, 24), date(2026, 11, 5)


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        (m(600), m(660), (date(2026, 11, 3), date(2026, 11, 3))),
        (m(1380), m(1500), (date(2026, 11, 3), date(2026, 11, 4))),  # across midnight
        (
            m(600),
            m(1440),
            (date(2026, 11, 3), date(2026, 11, 3)),
        ),  # ends at midnight: the next day is untouched
        (m(2000), m(4000), (date(2026, 11, 4), TODAY)),  # into today: later days do not exist yet
        (
            datetime(2025, 12, 1, tzinfo=UTC),
            datetime(2025, 12, 25, tzinfo=UTC),
            (COVERAGE, date(2025, 12, 24)),
        ),
    ],
)
def test_the_days_a_flag_recalculates(start: datetime, end: datetime, days: tuple[date, date]) -> None:
    assert flag_days(start, end, COVERAGE, TODAY) == days


def test_moving_a_flag_recalculates_both_places() -> None:
    a = (date(2026, 10, 2), date(2026, 10, 2))
    b = (date(2026, 10, 20), date(2026, 10, 21))
    assert union_days(a, b) == (date(2026, 10, 2), date(2026, 10, 21))
    assert union_days(None, b) == b and union_days(None, None) is None


# ---------------------------------------------------------------------------- the validity clause
def test_without_flags_the_condition_is_r1s() -> None:
    system = _system()
    atrh = system.sites[0].components[1]
    r1: dict[str, Any] = {}
    assert component_condition(system, atrh, r1) == component_condition(system, atrh, {}, {})
    assert component_condition(system, atrh, {}, {99: [flag(1, 0, 60)]}) == component_condition(
        system, atrh, {}
    )  # flags on another component change nothing here


def test_a_flagged_component_leaves_out_the_merged_ranges() -> None:
    system = _system()
    dcp, atrh = system.sites[0].components
    params: dict[str, Any] = {}
    cond = component_condition(
        system, atrh, params, {11: [flag(1, 0, 60), flag(2, 30, 90), flag(3, 200, 210)]}
    )
    assert cond.endswith(
        "NOT ((time >= :iv11_0a AND time < :iv11_0b) OR (time >= :iv11_1a AND time < :iv11_1b))"
    )
    assert (params["iv11_0a"], params["iv11_0b"], params["iv11_1a"]) == (m(0), m(90), m(200))
    assert "iv" not in component_condition(system, dcp, {}, {10: [flag(1, 0, 60)]})  # DCPs are never flagged


# ---------------------------------------------------------------------------- minute view
def test_only_valid_minutes_become_flagged_and_name_their_flag() -> None:
    codes = "vvvvnnffvvuu"
    got, owners = apply_invalid(T0, codes, [flag(4, 2, 10), flag(5, 0, 4)])
    assert got == "ggggnnffgguu"  # n, f and u keep their cause
    assert owners == [5, 5, 4, 4, 0, 0, 0, 0, 4, 4, 0, 0]  # 2-3 are under both: flag 4 came first
    runs = intervals(T0, got, owners, {4: "calibration", 5: "other"})
    flagged = sorted((r for r in runs if r["cause"] == "flagged"), key=lambda r: r["start"])
    assert [(r["minutes"], r["flags"]) for r in flagged] == [
        (2, [{"id": 5, "reason": "other"}]),
        (2, [{"id": 4, "reason": "calibration"}]),
        (2, [{"id": 4, "reason": "calibration"}]),
    ]


def test_runs_of_different_flags_stay_apart() -> None:
    got, owners = apply_invalid(T0, "vvvv", [flag(1, 0, 2), flag(2, 2, 4)])
    assert got == "gggg"
    assert [r["flags"][0]["id"] for r in sorted(intervals(T0, got, owners), key=lambda r: r["start"])] == [
        1,
        2,
    ]


# ---------------------------------------------------------------------------- outage breakdown
def test_flagged_outages_skip_minutes_already_lost() -> None:
    lost = [Outage(m(10), m(20), "field_missing", "04", "ATRH", ("RH",))]
    got = flagged_outages(
        window=(m(0), m(100)), lost=lost, invalid=[flag(7, 5, 30, "maintenance")], site="04", component="ATRH"
    )
    assert [(o.start, o.end, o.cause, o.flag, o.reason) for o in got] == [
        (m(5), m(10), "flagged", 7, "maintenance"),
        (m(20), m(30), "flagged", 7, "maintenance"),
    ]


def test_flagged_outages_stay_inside_the_window() -> None:
    got = flagged_outages(
        window=(m(50), m(60)), lost=[], invalid=[flag(1, 0, 100)], site="04", component="ATRH"
    )
    assert [(o.start, o.end) for o in got] == [(m(50), m(60))]
    assert (
        flagged_outages(window=(m(5), m(5)), lost=[], invalid=[flag(1, 0, 9)], site="04", component="X") == []
    )


@st.composite
def flagged_day(draw: st.DrawFn) -> dict[str, Any]:
    n = draw(st.integers(1, 120))
    codes = draw(st.lists(st.sampled_from("vvvfn"), min_size=n, max_size=n))
    lo = draw(st.integers(0, n))
    hi = draw(st.integers(lo, n))
    spans = draw(st.lists(st.tuples(st.integers(0, n), st.integers(1, 60)), max_size=4))
    return {
        "codes": codes,
        "window": (lo, hi),
        "flags": [flag(i + 1, a, a + w) for i, (a, w) in enumerate(spans)],
    }


@settings(max_examples=300, deadline=None)
@given(flagged_day())
def test_flags_cost_exactly_their_otherwise_valid_minutes(day: dict[str, Any]) -> None:
    """Minute view and outage breakdown agree minute by minute, and the KPI drops by exactly the flagged minutes."""
    lo, hi = day["window"]
    base = "".join(c if lo <= i < hi else "u" for i, c in enumerate(day["codes"]))
    flags: list[Invalid] = day["flags"]

    codes, owners = apply_invalid(T0, base, flags)
    lost = [Outage(m(i), m(i + 1), "no_record", "04", "ATRH") for i, c in enumerate(base) if c in "fn"]
    got = flagged_outages(window=(m(lo), m(hi)), lost=lost, invalid=flags, site="04", component="ATRH")

    per_minute: dict[int, int] = {}
    for o in got:
        for i in range(int((o.start - T0).total_seconds()) // 60, int((o.end - T0).total_seconds()) // 60):
            assert i not in per_minute, "flagged intervals overlap"
            assert o.flag is not None
            per_minute[i] = o.flag
    assert per_minute == {i: owners[i] for i, c in enumerate(codes) if c == "g"}
    for i, c in enumerate(codes):
        under = [f.source_id for f in flags if f.start <= m(i) < f.end]
        assert (c == "g") == (base[i] == "v" and bool(under))
        if c == "g":
            assert owners[i] == under[0]  # the older flag
    assert codes.count("v") == base.count("v") - sum(o.minutes for o in got)
