"""Outage breakdown (FR-KPI-009): interval assembly from runs, causes, grouping (pure functions).

The SQL that produces the runs is covered by the integration test on real files (CI) and was checked against
staging's real data: for 12 periods x 28 scopes the interval minutes equalled the KPI's missing minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from simola.kpi.outages import (
    CAUSES,
    Outage,
    Run,
    by_cause,
    complement,
    component_outages,
    down_outages,
    group,
    intersect_spans,
    join_adjacent,
    merge_spans,
    parse_scope,
    scope_counts,
)
from tests.unit.test_matrix_minutes import _system

T0 = datetime(2026, 11, 3, tzinfo=UTC)


def m(i: int) -> datetime:
    return T0 + timedelta(minutes=i)


def spans(*pairs: tuple[int, int]) -> list[tuple[datetime, datetime]]:
    return [(m(a), m(b)) for a, b in pairs]


# ---------------------------------------------------------------------------- spans
def test_span_helpers() -> None:
    assert merge_spans(spans((5, 8), (0, 2), (2, 3), (7, 9), (4, 4))) == spans((0, 3), (5, 9))
    assert complement(spans((2, 4), (6, 7)), (m(0), m(10))) == spans((0, 2), (4, 6), (7, 10))
    assert complement(spans((0, 10)), (m(2), m(5))) == []
    assert complement([], (m(2), m(5))) == spans((2, 5))
    assert intersect_spans(spans((0, 5), (8, 12)), spans((3, 9), (11, 20))) == spans((3, 5), (8, 9), (11, 12))


def test_join_adjacent_unites_fields() -> None:
    pieces = [
        Outage(m(5), m(7), "field_missing", "04", "ATRH", ("RH",)),
        Outage(m(0), m(5), "field_missing", "04", "ATRH", ("TEMP",)),
        Outage(m(7), m(9), "cdp_no_data", "04", "ATRH"),
    ]
    joined = join_adjacent(pieces)
    assert [(o.start, o.end, o.cause, o.fields) for o in joined] == [
        (m(0), m(7), "field_missing", ("TEMP", "RH")),
        (m(7), m(9), "cdp_no_data", ()),
    ]


# ---------------------------------------------------------------------------- one component
def test_component_outages_causes_and_fields() -> None:
    """A day fragment: record gaps with and without CDP data, and a run whose missing field changes."""
    present = spans((0, 10), (13, 20), (25, 30))  # no record at 10-13 and 20-25
    runs = [
        Run(m(3), m(5), bad=0b10, nulls=0b01),  # ATRH (bit 1) invalid: TEMP (bit 0) missing
        Run(m(5), m(6), bad=0b10, nulls=0b11),  # TEMP and RH missing: same outage continues
        Run(m(14), m(15), bad=0b01, nulls=0b11),  # only the DCP (bit 0) invalid: not ATRH's
    ]
    cdp_down = spans((10, 13), (22, 24))  # no CDP data at 10-13 and 22-24
    got = component_outages(
        window=(m(0), m(30)),
        present=present,
        runs=runs,
        cdp_down=cdp_down,
        bit=1,
        fields=[(0, "TEMP"), (1, "RH")],
        site="04",
        component="ATRH",
    )
    assert [(o.start, o.end, o.cause, o.fields) for o in got] == [
        (m(3), m(6), "field_missing", ("TEMP", "RH")),
        (m(10), m(13), "cdp_no_data", ()),
        (m(20), m(22), "no_record", ()),
        (m(22), m(24), "cdp_no_data", ()),
        (m(24), m(25), "no_record", ()),
    ]
    assert sum(o.minutes for o in got) == 3 + 3 + 5


def test_component_outages_clip_to_in_service_window() -> None:
    got = component_outages(
        window=(m(4), m(8)),  # in service from minute 4, period evaluated until minute 8
        present=spans((0, 2)),
        runs=[Run(m(0), m(2), bad=1, nulls=0)],
        cdp_down=spans((2, 10)),
        bit=0,
        fields=[],
        site="04",
        component="DCP",
    )
    assert [(o.start, o.end, o.cause) for o in got] == [(m(4), m(8), "cdp_no_data")]
    assert (
        component_outages(
            window=(m(5), m(5)),
            present=[],
            runs=[],
            cdp_down=[],
            bit=0,
            fields=[],
            site="04",
            component="DCP",
        )
        == []
    )


# ---------------------------------------------------------------------------- property: minute-by-minute
def _islands(minutes: list[int]) -> list[tuple[int, int]]:
    """Runs of consecutive minutes, like the SQL's `time - row_number()` grouping."""
    out: list[tuple[int, int]] = []
    for i in sorted(minutes):
        if out and out[-1][1] == i:
            out[-1] = (out[-1][0], i + 1)
        else:
            out.append((i, i + 1))
    return out


@st.composite
def site_day(draw: st.DrawFn) -> dict[str, object]:
    n = draw(st.integers(min_value=1, max_value=90))
    # Per minute: None = no merged record, else (bad mask over 3 components, nulls mask over 2 fields)
    states = draw(
        st.lists(
            st.one_of(st.none(), st.tuples(st.integers(0, 7), st.integers(0, 3))), min_size=n, max_size=n
        )
    )
    cdp_up = draw(st.lists(st.booleans(), min_size=n, max_size=n))
    lo = draw(st.integers(0, n))
    hi = draw(st.integers(lo, n))
    return {"n": n, "states": states, "cdp_up": cdp_up, "window": (lo, hi), "bit": draw(st.integers(0, 2))}


@settings(max_examples=300, deadline=None)
@given(site_day())
def test_outages_match_minute_by_minute_classification(day: dict[str, object]) -> None:
    """Every evaluated minute is lost exactly once, with the cause a per-minute reading gives (FR-KPI-009 AC1)."""
    n = day["n"]
    states: list[tuple[int, int] | None] = day["states"]  # type: ignore[assignment]
    cdp_up: list[bool] = day["cdp_up"]  # type: ignore[assignment]
    lo, hi = day["window"]  # type: ignore[misc]
    bit: int = day["bit"]  # type: ignore[assignment]
    assert isinstance(n, int)

    present = [(m(a), m(b)) for a, b in _islands([i for i, s in enumerate(states) if s is not None])]
    runs: list[Run] = []
    for key in {s for s in states if s is not None and s[0]}:
        for a, b in _islands([i for i, s in enumerate(states) if s == key]):
            runs.append(Run(m(a), m(b), key[0], key[1]))
    runs.sort(key=lambda r: r.start)
    down = [(m(a), m(b)) for a, b in _islands([i for i, up in enumerate(cdp_up) if not up])]

    got = component_outages(
        window=(m(lo), m(hi)),
        present=present,
        runs=runs,
        cdp_down=down,
        bit=bit,
        fields=[(0, "TEMP"), (1, "RH")],
        site="04",
        component="ATRH",
    )
    per_minute: dict[int, str] = {}
    for o in got:
        for i in range(int((o.start - T0).total_seconds() // 60), int((o.end - T0).total_seconds() // 60)):
            assert i not in per_minute, "intervals overlap"
            per_minute[i] = o.cause

    expected: dict[int, str] = {}
    for i in range(lo, hi):
        s = states[i]
        if s is None:
            expected[i] = "no_record" if cdp_up[i] else "cdp_no_data"
        elif (s[0] >> bit) & 1:
            expected[i] = "field_missing"
        # else: valid
    assert per_minute == expected
    valid = sum(1 for i in range(lo, hi) if states[i] is not None and not (states[i][0] >> bit) & 1)  # type: ignore[index]
    assert sum(o.minutes for o in got) == (hi - lo) - valid
    for a, b in pairwise(got):  # maximal: touching intervals differ in cause
        assert a.end < b.start or a.cause != b.cause


# ---------------------------------------------------------------------------- grouping and totals
def test_identical_intervals_are_grouped() -> None:
    gap = [Outage(m(10), m(13), "cdp_no_data", "04", t) for t in ("DCP", "ATRH")]
    long_field = Outage(m(0), m(5), "field_missing", "04", "ATRH", ("RH",))
    groups = group([*gap, long_field, Outage(m(20), m(23), "cdp_no_data", "04", "DCP")])
    assert [(g.start, g.minutes, len(g.members), g.lost) for g in groups] == [
        (m(0), 5, 1, 5),
        (m(10), 3, 2, 6),  # same length as the next one, but hits more components
        (m(20), 3, 1, 3),
    ]
    assert [o.component for o in groups[1].members] == ["DCP", "ATRH"]  # registry order kept
    sla = group(down_outages(spans((0, 4), (9, 10))))
    assert [(g.minutes, g.lost) for g in sla] == [(4, 4), (1, 1)]


def test_by_cause_reserves_r2_causes() -> None:
    totals = by_cause([Outage(m(0), m(3), "cdp_no_data"), Outage(m(5), m(6), "field_missing", "04", "ATRH")])
    assert list(totals) == list(CAUSES)
    assert totals == {"cdp_no_data": 3, "no_record": 0, "field_missing": 1, "flagged": 0, "detection": 0}


def test_parse_scope_and_counts() -> None:
    from simola.kpi.engine import Counts

    system = _system()
    counts = Counts()
    counts.add(("sla", 1), 1436, 1440)
    counts.add(("cdp_flow", 2), 1433, 1440)
    counts.add(("component", 10), 1430, 1440)
    counts.add(("component", 11), 1400, 1440)
    assert scope_counts(system, parse_scope(system, "sla"), counts) == (1436, 1440)
    assert scope_counts(system, parse_scope(system, "cdp:CDP2"), counts) == (1433, 1440)
    assert scope_counts(system, parse_scope(system, "component:04:ATRH"), counts) == (1400, 1440)
    assert scope_counts(system, parse_scope(system, "site:04"), counts) == (2830, 2880)
    assert scope_counts(system, parse_scope(system, "ola"), counts) == (2830, 2880)
    for bad in ("site:nope", "cdp:CDP9", "component:04:NOPE", "pooled"):
        with pytest.raises(ValueError, match="unknown scope"):
            parse_scope(system, bad)
