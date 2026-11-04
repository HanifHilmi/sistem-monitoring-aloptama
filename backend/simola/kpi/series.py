"""Sensor chart data (FR-DSH-008): gap-preserving downsampled numeric series, text-state data, wind rose."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.core.timeutil import MINUTE, floor_minute, intersect, minutes_between
from simola.kpi.engine import MINUTE_TABLE, clip_period, component_condition, grace_minutes, pct
from simola.registry import Component, Site, System

MAX_POINTS = 1000
FULL_RES_MINUTES = 1440  # windows up to 1 day are returned at full resolution
TEXT_TRANSITION_LIMIT = 2000
WIND_SPEED_CLASSES = (
    (0.0, 1.0, "calm"),
    (1.0, 10.0, "light"),
    (10.0, 20.0, "moderate"),
    (20.0, 30.0, "strong"),
    (30.0, math.inf, "gale"),
)


def lttb(points: list[tuple[float, float]], threshold: int) -> list[tuple[float, float]]:
    """Largest-Triangle-Three-Buckets downsampling (Steinarsson, 2013). Keeps first and last point."""
    n = len(points)
    if threshold >= n or threshold < 3:
        return list(points)
    sampled = [points[0]]
    every = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        avg_start = math.floor((i + 1) * every) + 1
        avg_end = min(math.floor((i + 2) * every) + 1, n)
        avg_x = sum(p[0] for p in points[avg_start:avg_end]) / max(1, avg_end - avg_start)
        avg_y = sum(p[1] for p in points[avg_start:avg_end]) / max(1, avg_end - avg_start)
        range_start = math.floor(i * every) + 1
        range_end = math.floor((i + 1) * every) + 1
        ax, ay = points[a]
        best_area, best = -1.0, range_start
        for j in range(range_start, range_end):
            area = abs((ax - avg_x) * (points[j][1] - ay) - (ax - points[j][0]) * (avg_y - ay))
            if area > best_area:
                best_area, best = area, j
        sampled.append(points[best])
        a = best
    sampled.append(points[-1])
    return sampled


def numeric_series(times: list[datetime], values: list[float | None], window_minutes: int) -> dict[str, Any]:
    """Split into gap-free segments, downsample each proportionally, join with null separators."""
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    prev: datetime | None = None
    for t, v in zip(times, values, strict=True):
        contiguous = prev is not None and t - prev == MINUTE
        if v is None or (current and not contiguous):
            if current:
                segments.append(current)
                current = []
        if v is not None:
            current.append((t.timestamp() * 1000.0, float(v)))
        prev = t
    if current:
        segments.append(current)

    total = sum(len(s) for s in segments)
    budget = MAX_POINTS if window_minutes > FULL_RES_MINUTES else total
    out_t: list[Any] = []
    out_v: list[Any] = []
    for i, seg in enumerate(segments):
        share = len(seg) if budget >= total else max(2, round(budget * len(seg) / max(1, total)))
        pts = lttb(seg, share)
        if i > 0:
            out_t.append(int(pts[0][0]) - 1)
            out_v.append(None)  # explicit break so charts do not draw across gaps
        out_t.extend(int(p[0]) for p in pts)
        out_v.extend(p[1] for p in pts)
    return {"t": out_t, "v": out_v, "downsampled": budget < total}


def text_series(times: list[datetime], values: list[str | None]) -> dict[str, Any]:
    transitions: list[list[Any]] = []
    prev: object = object()
    for t, v in zip(times, values, strict=True):
        if v != prev:
            if len(transitions) < TEXT_TRANSITION_LIMIT:
                transitions.append([int(t.timestamp() * 1000), v])
            prev = v
    counts = Counter(v for v in values if v is not None)
    return {
        "transitions": transitions,
        "truncated": len(transitions) >= TEXT_TRANSITION_LIMIT,
        "counts": [{"value": k, "minutes": n} for k, n in counts.most_common(20)],
        "missing_minutes": sum(1 for v in values if v is None),
    }


def wind_summary(
    ws: list[float | None], wd: list[float | None], gs: list[float | None], gd: list[float | None]
) -> dict[str, Any]:
    rose = [dict.fromkeys([c[2] for c in WIND_SPEED_CLASSES], 0) for _ in range(16)]
    speeds = []
    for s, d in zip(ws, wd, strict=True):
        if s is None or d is None:
            continue
        speeds.append(s)
        sector = int(((d % 360.0) + 11.25) // 22.5) % 16  # 16 sectors centred on N, NNE, ...
        cls = next(c[2] for c in WIND_SPEED_CLASSES if c[0] <= s < c[1])
        rose[sector][cls] += 1
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
    cond = component_condition(system, comp, params)
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
                f"SELECT time, {cols} FROM {MINUTE_TABLE[system.type_code]} "
                "WHERE site_id = :s AND time >= :a AND time < :b ORDER BY time"
            ),
            {"s": site.id, "a": start, "b": end},
        )
    ).all()
    times = [r[0] for r in rows]
    out_fields = []
    columns: dict[str, list[Any]] = {}
    for idx, f in enumerate(fields, start=1):
        vals = [r[idx] for r in rows]
        columns[f.code] = vals
        entry: dict[str, Any] = {
            "code": f.code,
            "unit": f.unit,
            "type": f.value_type,
            "mandatory": f.code in comp.mandatory,
        }
        if f.is_text:
            entry["text"] = text_series(times, vals)
        else:
            entry["series"] = numeric_series(times, vals, window_minutes)
        out_fields.append(entry)
    result: dict[str, Any] = {
        "fields": out_fields,
        "availability": await component_window_availability(conn, system, comp, start, end, now),
    }
    if comp.type_code == "ANEM" and {"WS", "WD", "WGS", "WGD"} <= set(columns):
        result["wind"] = wind_summary(columns["WS"], columns["WD"], columns["WGS"], columns["WGD"])
    return result


def max_series_window() -> timedelta:
    return timedelta(days=31)
