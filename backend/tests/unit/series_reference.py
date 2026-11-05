"""Reference copy of the chart functions as they were before the speed rewrite (2026-11-05).

Used only by test_series_equivalence.py: the fast versions must return exactly what these return.
Do not change this file to make a test pass.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from simola.core.timeutil import MINUTE

MAX_POINTS = 1000
FULL_RES_MINUTES = 1440
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


def field_stats(times: list[datetime], values: list[Any], *, numeric: bool) -> dict[str, Any]:
    """Latest value plus min/max/mean over the raw 1-minute data of the window (not the downsampled points)."""
    last = next(
        ((t, v) for t, v in zip(reversed(times), reversed(values), strict=True) if v is not None), None
    )
    out: dict[str, Any] = {
        "last": {"time": last[0], "value": last[1]} if last else None,
        "count": sum(1 for v in values if v is not None),
    }
    if numeric:
        nums = [float(v) for v in values if v is not None]
        out.update(
            min=min(nums) if nums else None,
            max=max(nums) if nums else None,
            mean=round(sum(nums) / len(nums), 3) if nums else None,
        )
    return out


# Frozen 2026-11-05 from simola/kpi/sensors.py before the speed-up (MAX_DOTS = 1000, FULL_RES_MINUTES = 1440).
DOT_MAX = 1000
DOT_FULL_RES = 1440


def dot_series(
    ms: Sequence[int], values: Sequence[float | None], window_minutes: int, *, zero_is_none: bool = False
) -> dict[str, Any]:
    """Readings as dots, without gaps or joins. Windows over a day keep each time bucket's lowest and highest
    reading (in time order), so the lowest cloud bases and the extreme directions always show."""
    pts = [
        (t, float(v))
        for t, v in zip(ms, values, strict=True)
        if v is not None and not (zero_is_none and v == 0)
    ]
    if window_minutes <= DOT_FULL_RES or len(pts) <= 2 * DOT_MAX:
        return {"t": [p[0] for p in pts], "v": [p[1] for p in pts], "downsampled": False}
    first, span = pts[0][0], max(1, pts[-1][0] - pts[0][0] + 1)
    buckets: dict[int, tuple[tuple[int, float], tuple[int, float]]] = {}
    for p in pts:
        b = (p[0] - first) * DOT_MAX // span
        lo_hi = buckets.get(b)
        if lo_hi is None:
            buckets[b] = (p, p)
        else:
            lo, hi = lo_hi
            buckets[b] = (p if p[1] < lo[1] else lo, p if p[1] > hi[1] else hi)
    kept: list[tuple[int, float]] = []
    for b in sorted(buckets):
        lo, hi = buckets[b]
        kept.extend(sorted({lo, hi}))
    return {"t": [p[0] for p in kept], "v": [p[1] for p in kept], "downsampled": True}
