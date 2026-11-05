"""Pure KPI maths: rounding, grace window, downsampling (FR-KPI-003/007, FR-DSH-008)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from simola.core.timeutil import minutes_between
from simola.kpi.engine import evaluation_end, pct
from simola.kpi.series import lttb, numeric_series, wind_summary


def test_pct_rounds_half_up() -> None:
    assert pct(1, 800) == 0.13  # 0.125 -> 0.13 (half-up, not banker's rounding)
    assert pct(2, 3) == 66.67
    assert pct(43200, 43200) == 100.0


def test_pct_none_when_nothing_expected() -> None:
    assert pct(0, 0) is None


def test_pct_rejects_impossible_counts() -> None:
    with pytest.raises(AssertionError):
        pct(43201, 43200)  # v2 reported this for September 2026 (ASSESSMENT D-09)


@given(st.integers(min_value=0, max_value=10**7), st.integers(min_value=1, max_value=10**7))
def test_pct_bounds(valid: int, expected: int) -> None:
    valid = min(valid, expected)
    value = pct(valid, expected)
    assert value is not None and 0.0 <= value <= 100.0


def test_grace_window_example_from_prd() -> None:
    """FR-KPI-003 AC1: at 10:30:00 UTC with G = 3, today's expected minutes are 627."""
    now = datetime(2026, 11, 4, 10, 30, tzinfo=UTC)
    midnight = datetime(2026, 11, 4, tzinfo=UTC)
    assert minutes_between(midnight, evaluation_end(now, 3)) == 627


def test_september_has_exactly_43200_minutes() -> None:
    assert minutes_between(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)) == 43200


def ms(times: list[datetime]) -> list[int]:
    return [int(t.timestamp() * 1000) for t in times]


def test_lttb_keeps_endpoints_and_size() -> None:
    xs = [float(i) for i in range(5000)]
    ys = [float((i * 7) % 13) for i in range(5000)]
    out = lttb(xs, ys, 500)
    assert len(out) == 500 and out[0] == 0 and out[-1] == 4999


def test_numeric_series_breaks_at_gaps() -> None:
    t0 = datetime(2026, 11, 3, tzinfo=UTC)
    times = [t0 + timedelta(minutes=i) for i in range(10) if i != 4]  # minute 4 has no record
    values: list[float | None] = [1.0 if i != 7 else None for i in range(10) if i != 4]  # minute 7 missing
    out = numeric_series(ms(times), values, window_minutes=10)
    assert out["v"].count(None) == 2  # two breaks: missing record and missing value
    assert out["downsampled"] is False


def test_numeric_series_downsamples_long_windows() -> None:
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    n = 31 * 1440
    times = [t0 + timedelta(minutes=i) for i in range(n)]
    out = numeric_series(ms(times), [float(i % 97) for i in range(n)], window_minutes=n)
    assert out["downsampled"] is True and len(out["t"]) <= 1000


def test_wind_rose_sectors_centred_on_north() -> None:
    out = wind_summary([5.0, 5.0, 5.0], [355.0, 5.0, 12.0], [0.0, 0.0, 8.0], [0.0, 0.0, 15.0])
    assert out["rose"][0]["light"] == 2  # 355 and 5 degrees are both N
    assert out["rose"][1]["light"] == 1  # 12 degrees is NNE
    assert out["gust"] == {"count": 1, "max_speed_kt": 8.0, "direction_deg": 15.0}
