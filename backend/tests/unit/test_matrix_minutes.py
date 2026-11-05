"""Board matrix bucketing and minute-status assembly (pure functions)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from simola.kpi.engine import Counts
from simola.kpi.matrix import bucket_end, bucket_starts, build_matrix
from simola.kpi.minutes import intervals, statuses
from simola.registry import Cdp, Component, MetricField, Site, System


def _system() -> System:
    def comp(cid: int, t: str, dcp: bool, fields: tuple[str, ...], mand: tuple[str, ...]) -> Component:
        return Component(cid, 1, t, dcp, t, t, cid, fields, mand, None, None)

    site = Site(
        1,
        "RWY04",
        "04",
        "04",
        "Runway 04",
        "Landasan 04",
        1,
        (comp(10, "DCP", True, (), ()), comp(11, "ATRH", False, ("TEMP", "RH"), ("TEMP", "RH"))),
    )
    fields = {
        "TEMP": MetricField("TEMP", "temp_c", "numeric", "°C", "t", "t", 1),
        "RH": MetricField("RH", "rh_pct", "numeric", "%", "r", "r", 2),
    }
    return System(
        1,
        "S",
        "AWOS_CAT3",
        "sla_ola",
        "S",
        "S",
        "WIDN",
        datetime(2025, 12, 24, tzinfo=UTC),
        (Cdp(1, "CDP1", 1), Cdp(2, "CDP2", 2)),
        (site,),
        fields,
    )


def _day(sla: int, c1: int, dcp: int, atrh: int) -> Counts:
    c = Counts()
    c.add(("sla", 1), sla, 1440)
    c.add(("cdp_flow", 1), c1, 1440)
    c.add(("cdp_flow", 2), 1440, 1440)
    c.add(("component", 10), dcp, 1440)
    c.add(("component", 11), atrh, 1440)
    return c


def test_bucket_starts_clip_to_period() -> None:
    # November 2026 starts on a Sunday: the first ISO week bucket is clipped to Nov 1.
    assert bucket_starts(date(2026, 11, 1), date(2026, 11, 30), "week") == [
        date(2026, 11, 1),
        date(2026, 11, 2),
        date(2026, 11, 9),
        date(2026, 11, 16),
        date(2026, 11, 23),
        date(2026, 11, 30),
    ]
    assert len(bucket_starts(date(2026, 11, 1), date(2026, 11, 30), "day")) == 30
    assert bucket_starts(date(2026, 10, 1), date(2026, 12, 31), "month") == [
        date(2026, 10, 1),
        date(2026, 11, 1),
        date(2026, 12, 1),
    ]


def test_bucket_end() -> None:
    assert bucket_end(date(2026, 12, 1), "month") == date(2027, 1, 1)
    assert bucket_end(date(2026, 11, 1), "week") == date(2026, 11, 2)  # Sunday ends the ISO week


def test_matrix_totals_equal_sum_of_cells() -> None:
    system = _system()
    days = {date(2026, 11, 1): _day(1440, 1430, 1440, 1400), date(2026, 11, 2): _day(1436, 1433, 1436, 1436)}
    m = build_matrix(system, days, date(2026, 11, 1), date(2026, 11, 3), "day")
    assert len(m["buckets"]) == 3
    rows = {r["key"]: r for r in m["rows"]}
    assert list(rows) == [
        "sla",
        "cdp:CDP1",
        "cdp:CDP2",
        "ola",
        "site:04",
        "component:04:DCP",
        "component:04:ATRH",
    ]
    sla = rows["sla"]
    assert sla["total"] == {"valid": 2876, "expected": 2880, "missing": 4, "pct": 99.86}
    assert sla["cells"][2] == {"valid": 0, "expected": 0, "missing": 0, "pct": None}  # day without data
    atrh = rows["component:04:ATRH"]
    assert sum(c["valid"] for c in atrh["cells"]) == atrh["total"]["valid"] == 2836
    site = rows["site:04"]
    assert site["total"]["valid"] == 1440 + 1436 + 1400 + 1436


def test_minute_statuses_and_intervals() -> None:
    start = datetime(2026, 11, 3, tzinfo=UTC)
    m = [start + timedelta(minutes=i) for i in range(10)]
    evaluable = [True] * 8 + [False, False]
    present = set(m[:6])  # minutes 6,7 have no record
    valid = set(m[:6]) - {m[2], m[3]}  # minutes 2,3 have a missing mandatory field
    codes = statuses(start, evaluable, present, valid)
    assert codes == "vvffvvnnuu"
    runs = intervals(start, codes)
    assert [(r["cause"], r["minutes"]) for r in runs] == [("field_missing", 2), ("no_data", 2)]
    assert runs[0]["start"] == m[2] and runs[0]["end"] == m[4]


def test_group_key_matches_matrix_buckets() -> None:
    from simola.kpi.engine import group_key
    from simola.kpi.matrix import bucket_start

    first = date(2026, 10, 7)  # a Wednesday
    for offset in range(60):
        d = first + timedelta(days=offset)
        for bucket in ("day", "week", "month"):
            assert group_key(d, bucket, first) == max(bucket_start(d, bucket), first)
    assert group_key(date(2026, 12, 31), "all", first) == first
