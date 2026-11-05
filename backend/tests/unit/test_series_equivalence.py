"""The fast chart functions return exactly what the original ones did (FR-DSH-008 output must not change)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from simola.kpi import series as fast
from tests.unit import series_reference as ref

T0 = datetime(2026, 10, 1, tzinfo=UTC)
T0_MS = int(T0.timestamp() * 1000)


def minute_rows(seed: int, n: int, gap_rate: float) -> tuple[list[int], list[datetime]]:
    """n row minutes in time order, with occasional missing records (gaps of 1-90 minutes)."""
    rnd = random.Random(seed)
    k, minutes = 0, []
    for _ in range(n):
        if rnd.random() < gap_rate:
            k += rnd.randint(1, 90)
        minutes.append(k)
        k += 1
    return [T0_MS + m * 60_000 for m in minutes], [T0 + timedelta(minutes=m) for m in minutes]


def numbers(seed: int, n: int, none_rate: float, lo: float, hi: float) -> list[float | None]:
    rnd = random.Random(seed + 1)
    return [
        None if rnd.random() < none_rate else round(rnd.uniform(lo, hi), rnd.choice((0, 1, 3)))
        for _ in range(n)
    ]


shapes = st.tuples(
    st.integers(0, 2**32),
    st.sampled_from([0, 1, 2, 3, 10, 999, 1000, 1001, 1440, 5000, 44_640]),
    st.sampled_from([0.0, 0.001, 0.02, 0.3]),
    st.sampled_from([0.0, 0.01, 0.2, 0.9, 1.0]),
)


@settings(max_examples=80, deadline=None)
@given(shapes, st.sampled_from([60, 1440, 1441, 10_080, 44_640]))
def test_numeric_series_is_unchanged(shape: tuple[int, int, float, float], window: int) -> None:
    seed, n, gap_rate, none_rate = shape
    ms, times = minute_rows(seed, n, gap_rate)
    values = numbers(seed, n, none_rate, -40.0, 1500.0)
    assert fast.numeric_series(ms, values, window) == ref.numeric_series(times, values, window)


@settings(max_examples=60, deadline=None)
@given(shapes)
def test_field_stats_are_unchanged(shape: tuple[int, int, float, float]) -> None:
    seed, n, gap_rate, none_rate = shape
    ms, times = minute_rows(seed, n, gap_rate)
    values = numbers(seed, n, none_rate, -40.0, 1500.0)
    assert fast.field_stats(ms, values, numeric=True) == ref.field_stats(times, values, numeric=True)
    words: list[Any] = [None if v is None else f"W{int(v) % 4}" for v in values]
    assert fast.field_stats(ms, words, numeric=False) == ref.field_stats(times, words, numeric=False)


@settings(max_examples=60, deadline=None)
@given(shapes)
def test_text_series_is_unchanged(shape: tuple[int, int, float, float]) -> None:
    seed, n, gap_rate, none_rate = shape
    ms, times = minute_rows(seed, n, gap_rate)
    rnd = random.Random(seed)
    values = [
        None if rnd.random() < none_rate else rnd.choice(["RA", "-RA", "+TSRA", "BR", ""]) for _ in range(n)
    ]
    assert fast.text_series(ms, values) == ref.text_series(times, values)


@settings(max_examples=60, deadline=None)
@given(shapes)
def test_wind_summary_is_unchanged(shape: tuple[int, int, float, float]) -> None:
    seed, n, _, none_rate = shape
    ws = numbers(seed, n, none_rate, 0.0, 45.0)
    wd = numbers(seed + 7, n, none_rate, 0.0, 360.0)
    gs = numbers(seed + 11, n, none_rate, 0.0, 60.0)
    gd = numbers(seed + 13, n, none_rate, 0.0, 360.0)
    # Class edges exactly.
    ws[: min(n, 6)] = [0.0, 1.0, 10.0, 20.0, 30.0, 0.999][: min(n, 6)]
    assert fast.wind_summary(ws, wd, gs, gd) == ref.wind_summary(ws, wd, gs, gd)


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 2**32), st.integers(0, 6000), st.integers(0, 1200))
def test_lttb_picks_the_same_points(seed: int, n: int, threshold: int) -> None:
    rnd = random.Random(seed)
    xs = [T0_MS + i * 60_000 for i in range(n)]
    ys = [rnd.choice([rnd.uniform(-5, 5), 0.0, 1.0]) for _ in range(n)]  # many ties on purpose
    expected = ref.lttb([(float(x), y) for x, y in zip(xs, ys, strict=True)], threshold)
    got = [(float(xs[i]), ys[i]) for i in fast.lttb(xs, ys, threshold)]
    assert got == expected


def test_a_full_31_day_window_is_unchanged() -> None:
    # Fragmentation like staging's (tens of breaks a month), not the worst case.
    ms, times = minute_rows(42, 44_640, 0.0003)
    values = numbers(42, 44_640, 0.0002, 990.0, 1030.0)
    out = fast.numeric_series(ms, values, 44_640)
    assert out == ref.numeric_series(times, values, 44_640)
    assert out["downsampled"] is True and len(out["t"]) < 1300
