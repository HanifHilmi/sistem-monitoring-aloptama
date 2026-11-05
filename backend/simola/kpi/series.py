"""Sensor chart data (FR-DSH-008): gap-preserving downsampled numeric series, text-state data, wind rose."""

from __future__ import annotations

import asyncio
import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import floor_minute, intersect, minutes_between
from simola.kpi import sensors
from simola.kpi.engine import (
    MINUTE_TABLE,
    clip_period,
    component_condition,
    grace_minutes,
    invalid_intervals,
    pct,
)
from simola.registry import Component, MetricField, Site, System

MAX_POINTS = 1000
# How some fields are charted (agreed with the user 2026-11-05; field codes of the AWOS registry).
DOT_FIELDS = frozenset({"WD", "LR1"})  # dots: a direction line jumps at 360/0; cloud bases are not a curve
ZERO_IS_NONE = frozenset({"LR1"})  # cloud base 0 = no cloud detected: not a reading for the chart or figures
GUST_FIELDS = frozenset({"WGS", "WGD"})  # shown as gust events (sensors.gust_events), not as lines
TEXT_SUMMARIES = {
    "SKY": ("sky", sensors.sky_summary),
    "PW": ("weather", sensors.weather_summary),
    "LTX": ("lightning", sensors.lightning_summary),
}
FULL_RES_MINUTES = 1440  # windows up to 1 day are returned at full resolution
TEXT_TRANSITION_LIMIT = 2000
WIND_SPEED_CLASSES = (
    (0.0, 1.0, "calm"),
    (1.0, 10.0, "light"),
    (10.0, 20.0, "moderate"),
    (20.0, 30.0, "strong"),
    (30.0, math.inf, "gale"),
)
_CLASS_FLOORS = tuple(c[0] for c in WIND_SPEED_CLASSES)
MINUTE_MS = 60_000


def lttb(xs: Sequence[float], ys: Sequence[float], threshold: int) -> list[int]:
    """Largest-Triangle-Three-Buckets downsampling (Steinarsson, 2013): the indices of the kept points.

    Keeps the first and last point. Plain lists and hoisted terms keep it fast in pure Python; the arithmetic is
    the textbook one term for term, so the same points are chosen as by a straightforward implementation.
    """
    n = len(xs)
    if threshold >= n or threshold < 3:
        return list(range(n))
    kept = [0]
    every = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        avg_start = math.floor((i + 1) * every) + 1
        avg_end = min(math.floor((i + 2) * every) + 1, n)
        span = max(1, avg_end - avg_start)
        avg_x = sum(xs[avg_start:avg_end]) / span
        avg_y = sum(ys[avg_start:avg_end]) / span
        range_start = math.floor(i * every) + 1
        range_end = math.floor((i + 1) * every) + 1
        ax, ay = xs[a], ys[a]
        dx, dy = ax - avg_x, avg_y - ay
        areas = [
            abs(dx * (y - ay) - (ax - x) * dy)
            for x, y in zip(xs[range_start:range_end], ys[range_start:range_end], strict=True)
        ]
        best = range_start
        if areas:
            top = max(areas)
            if top == top:  # first point with the largest area, as a strict ">" scan would pick
                best += areas.index(top)
            else:  # a NaN came first: fall back to the scan, which skips NaN areas
                best_area = -1.0
                for j, area in enumerate(areas, start=range_start):
                    if area > best_area:
                        best_area, best = area, j
        kept.append(best)
        a = best
    kept.append(n - 1)
    return kept


def numeric_series(ms: Sequence[int], values: Sequence[float | None], window_minutes: int) -> dict[str, Any]:
    """Split into gap-free segments, downsample each proportionally, join with null separators.

    `ms` holds each row's minute as epoch milliseconds (rows are whole minutes, in time order).
    """
    # Segment boundaries: a missing value ends a segment, a missing minute (time jump) starts a new one.
    stops = sorted(
        [(i, 0) for i, (a, b) in enumerate(pairwise(ms), start=1) if b - a != MINUTE_MS]
        + [(i, 1) for i, v in enumerate(values) if v is None]
    )
    spans: list[tuple[int, int]] = []
    begin = 0
    for i, skip in stops:
        if i > begin:
            spans.append((begin, i))
        begin = i + skip
    if len(ms) > begin:
        spans.append((begin, len(ms)))
    seg_x = [ms[a:b] for a, b in spans]
    # Spans hold no None, so every value converts.
    seg_y = [list(map(float, values[a:b])) for a, b in spans]  # type: ignore[arg-type]

    total = sum(len(x) for x in seg_x)
    budget = MAX_POINTS if window_minutes > FULL_RES_MINUTES else total
    out_t: list[Any] = []
    out_v: list[Any] = []
    for i, (xs, ys) in enumerate(zip(seg_x, seg_y, strict=True)):
        if i > 0:
            out_t.append(xs[0] - 1)
            out_v.append(None)  # explicit break so charts do not draw across gaps
        if budget >= total:
            out_t.extend(xs)
            out_v.extend(ys)
            continue
        idx = lttb(xs, ys, max(2, round(budget * len(xs) / max(1, total))))
        out_t.extend([xs[k] for k in idx])
        out_v.extend([ys[k] for k in idx])
    return {"t": out_t, "v": out_v, "downsampled": budget < total}


def text_series(ms: Sequence[int], values: Sequence[str | None]) -> dict[str, Any]:
    transitions: list[list[Any]] = []
    prev: object = object()
    for t, v in zip(ms, values, strict=True):
        if v != prev:
            if len(transitions) < TEXT_TRANSITION_LIMIT:
                transitions.append([t, v])
            prev = v
    counts = Counter(v for v in values if v is not None)
    return {
        "transitions": transitions,
        "truncated": len(transitions) >= TEXT_TRANSITION_LIMIT,
        "counts": [{"value": k, "minutes": n} for k, n in counts.most_common(20)],
        "missing_minutes": values.count(None),
    }


def wind_summary(
    ws: Sequence[float | None],
    wd: Sequence[float | None],
    gs: Sequence[float | None],
    gd: Sequence[float | None],
) -> dict[str, Any]:
    names = [c[2] for c in WIND_SPEED_CLASSES]
    pairs = [(s, d) for s, d in zip(ws, wd, strict=True) if s is not None and d is not None]
    speeds = [s for s, _ in pairs]
    # 16 sectors centred on N, NNE, ...; the speed classes are contiguous from 0 kt, so their lower bounds
    # decide the class (below 0 counts as calm).
    cells = Counter(
        (int(((d % 360.0) + 11.25) // 22.5) % 16, bisect_right(_CLASS_FLOORS, s)) for s, d in pairs
    )
    rose = [dict.fromkeys(names, 0) for _ in range(16)]
    for (sector, k), n in cells.items():
        rose[sector][names[max(0, k - 1)]] += n
    gust_events = [(g, d) for g, d in zip(gs, gd, strict=True) if g is not None and g > 0]
    top = max(gust_events, key=lambda x: x[0]) if gust_events else None
    return {
        "rose": [{"sector": i, **r} for i, r in enumerate(rose)],
        "max_speed_kt": max(speeds) if speeds else None,
        "min_speed_kt": min(speeds) if speeds else None,
        "gust": {
            "count": len(gust_events),
            "max_speed_kt": top[0] if top else None,
            "direction_deg": top[1] if top else None,
        },
    }


def field_stats(ms: Sequence[int], values: Sequence[Any], *, numeric: bool) -> dict[str, Any]:
    """Latest value plus min/max/mean over the raw 1-minute data of the window (not the downsampled points)."""
    last = next(((t, v) for t, v in zip(reversed(ms), reversed(values), strict=True) if v is not None), None)
    nums = [float(v) for v in values if v is not None] if numeric else []
    out: dict[str, Any] = {
        "last": {"time": datetime.fromtimestamp(last[0] / 1000, UTC), "value": last[1]} if last else None,
        "count": len(values) - values.count(None),
    }
    if numeric:
        out.update(
            min=min(nums) if nums else None,
            max=max(nums) if nums else None,
            mean=round(sum(nums) / len(nums), 3) if nums else None,
        )
    return out


async def component_window_availability(
    conn: AsyncConnection, system: System, comp: Component, start: datetime, end: datetime, now: datetime
) -> dict[str, Any]:
    g = await grace_minutes(conn)
    a, b = clip_period(system, start, end, now, g)
    wa, wb = intersect((a, b), (comp.in_service_from, comp.in_service_to))
    expected = minutes_between(wa, wb)
    if expected <= 0:
        return {"valid": 0, "expected": 0, "missing": 0, "pct": None}
    params: dict[str, Any] = {"a": wa, "b": wb}
    invalid = await invalid_intervals(conn, [] if comp.is_dcp else [comp.id], wa, wb)
    cond = component_condition(system, comp, params, invalid)
    valid = (
        await conn.execute(
            text(
                f"SELECT count(*) FILTER (WHERE {cond}) FROM {MINUTE_TABLE[system.type_code]} "
                f"WHERE site_id = {int(comp.site_id)} AND time >= :a AND time < :b"
            ),
            params,
        )
    ).scalar_one()
    return {
        "valid": int(valid),
        "expected": expected,
        "missing": expected - int(valid),
        "pct": pct(int(valid), expected),
    }


async def component_series(
    conn: AsyncConnection,
    system: System,
    site: Site,
    comp: Component,
    start: datetime,
    end: datetime,
    now: datetime,
) -> dict[str, Any]:
    start, end = floor_minute(start), floor_minute(end)
    window_minutes = minutes_between(start, end)
    fields = [system.fields[f] for f in comp.fields]
    if comp.is_dcp:
        return {
            "fields": [],
            "availability": await component_window_availability(conn, system, comp, start, end, now),
        }
    cols = ", ".join(f.column for f in fields)
    rows = (
        await conn.execute(
            text(
                # Epoch milliseconds straight from the database: cheaper than 44,640 datetime objects.
                f"SELECT (extract(epoch FROM time) * 1000)::bigint, {cols} FROM {MINUTE_TABLE[system.type_code]} "
                "WHERE site_id = :s AND time >= :a AND time < :b ORDER BY time"
            ),
            {"s": site.id, "a": start, "b": end},
        )
    ).all()
    availability = await component_window_availability(conn, system, comp, start, end, now)
    # Building the chart is pure Python (up to ~0.3 s for 31 days). On a thread, this API process keeps
    # answering other requests meanwhile instead of making them wait until the chart is done.
    return await asyncio.to_thread(_build, comp, fields, rows, window_minutes, availability)


def _build(
    comp: Component,
    fields: list[MetricField],
    rows: Sequence[Sequence[Any]],
    window_minutes: int,
    availability: dict[str, Any],
) -> dict[str, Any]:
    by_column: list[tuple[Any, ...]] = list(zip(*rows, strict=True)) if rows else [()] * (len(fields) + 1)
    times = by_column[0]
    out_fields = []
    columns: dict[str, tuple[Any, ...]] = {}
    for idx, f in enumerate(fields, start=1):
        vals = by_column[idx]
        columns[f.code] = vals
        entry: dict[str, Any] = {
            "code": f.code,
            "unit": f.unit,
            "type": f.value_type,
            "mandatory": f.code in comp.mandatory,
        }
        if f.is_text:
            entry["text"] = text_series(times, vals)
            if f.code in TEXT_SUMMARIES:
                key, summarize = TEXT_SUMMARIES[f.code]
                entry[key] = summarize(times, vals, window_minutes)
        elif f.code in GUST_FIELDS:
            entry["chart"] = "gust"
            entry["series"] = {"t": [], "v": [], "downsampled": False}
        elif f.code in DOT_FIELDS:
            entry["chart"] = "dots"
            entry["series"] = sensors.dot_series(
                times, vals, window_minutes, zero_is_none=f.code in ZERO_IS_NONE
            )
        else:
            entry["chart"] = "line"
            entry["series"] = numeric_series(times, vals, window_minutes)
        entry["stats"] = field_stats(times, vals, numeric=not f.is_text)
        if f.code in ZERO_IS_NONE:
            entry["stats"] = sensors.nonzero_stats(entry["stats"], vals)
        out_fields.append(entry)
    result: dict[str, Any] = {"fields": out_fields, "availability": availability}
    if comp.type_code == "ANEM" and {"WS", "WD", "WGS", "WGD"} <= set(columns):
        result["wind"] = wind_summary(columns["WS"], columns["WD"], columns["WGS"], columns["WGD"])
        result["wind"]["gust"].update(sensors.gust_events(times, columns["WGS"], columns["WGD"]))
    return result


def max_series_window() -> timedelta:
    return timedelta(days=31)
