"""Chart data for sensors that a plain line does not explain (FR-DSH-008, agreed with the user 2026-11-05).

- Dots: wind direction and cloud base. A line would jump between 359° and 0°, and a cloud base of 0 means
  "no cloud detected", not a cloud on the ground, so those minutes are left out of the dots and the figures.
- Gusts: the events (unbroken minutes with a gust), the strongest one and when it happened.
- Sky condition: the cloud layers by height band (low, middle, high) and coverage (FEW, SCT, BKN, OVC).
- Present weather: METAR codes grouped into rows (thunderstorm, rain, drizzle, mist and fog, haze, other).
- Lightning: how close the storm was (at the airport, in the vicinity, distant) and where distant lightning was.

All functions take the rows of the window as epoch milliseconds (whole minutes, in time order) and values.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache
from itertools import pairwise
from typing import Any

MINUTE_MS = 60_000
MAX_DOTS = 1000  # buckets for windows over a day; each keeps its lowest and highest reading
FULL_RES_MINUTES = 1440

# ---------------------------------------------------------------------------- dots


def dot_series(
    ms: Sequence[int], values: Sequence[float | None], window_minutes: int, *, zero_is_none: bool = False
) -> dict[str, Any]:
    """Readings as dots, without gaps or joins. Windows over a day keep each time bucket's lowest and highest
    reading (in time order), so the lowest cloud bases and the extreme directions always show."""
    ts: list[int] = []
    vs: list[float] = []
    for t, v in zip(ms, values, strict=True):
        if v is not None and not (zero_is_none and v == 0):
            ts.append(t)
            vs.append(float(v))
    if window_minutes <= FULL_RES_MINUTES or len(ts) <= 2 * MAX_DOTS:
        return {"t": ts, "v": vs, "downsampled": False}
    # Times are in order, so each bucket is one slice: find the slice ends by bisection and take each
    # slice's first lowest and first highest reading with min/max (31 days: ~5x faster than point by point).
    first, span = ts[0], max(1, ts[-1] - ts[0] + 1)
    cuts = [0]
    cuts += (bisect_left(ts, first + (b * span + MAX_DOTS - 1) // MAX_DOTS) for b in range(1, MAX_DOTS))
    cuts.append(len(ts))
    kt: list[int] = []
    kv: list[float] = []
    for i, j in pairwise(cuts):
        if i == j:
            continue
        chunk = vs[i:j]
        lo, hi = i + chunk.index(min(chunk)), i + chunk.index(max(chunk))
        for k in (lo,) if lo == hi else sorted((lo, hi)):
            kt.append(ts[k])
            kv.append(vs[k])
    return {"t": kt, "v": kv, "downsampled": True}


def nonzero_stats(stats: dict[str, Any], values: Sequence[float | None]) -> dict[str, Any]:
    """Cloud base figures without the "no cloud" zeros: min/max/mean of cloudy minutes and the zero count."""
    nums = [float(v) for v in values if v is not None and v != 0]
    out = dict(stats)
    out.update(
        count=len(nums),
        zero_minutes=sum(1 for v in values if v == 0),
        min=min(nums) if nums else None,
        max=max(nums) if nums else None,
        mean=round(sum(nums) / len(nums), 3) if nums else None,
    )
    return out


# ---------------------------------------------------------------------------- gusts


def _time(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


def gust_events(
    ms: Sequence[int], gs: Sequence[float | None], gd: Sequence[float | None], *, limit: int = 200
) -> dict[str, Any]:
    """Gust events: unbroken runs of minutes with a gust above 0. A missing minute or a 0 ends an event.

    Each event has its start, length, strongest gust and that gust's direction (the first if it repeats).
    """
    events: list[dict[str, Any]] = []
    run: list[tuple[int, float, float | None]] = []

    def close() -> None:
        if run:
            top = max(run, key=lambda r: r[1])  # first of equal maxima
            events.append(
                {"start": _time(run[0][0]), "minutes": len(run), "max_kt": top[1], "direction_deg": top[2]}
            )
            run.clear()

    prev: int | None = None
    for t, g, d in zip(ms, gs, gd, strict=True):
        if g is None or g <= 0 or (run and prev is not None and t - prev != MINUTE_MS):
            close()
        if g is not None and g > 0:
            run.append((t, float(g), d))
        prev = t
    close()
    strongest = max(events, key=lambda e: e["max_kt"]) if events else None
    return {
        "event_count": len(events),
        "minutes": sum(e["minutes"] for e in events),
        "strongest": strongest,
        "events": events[-limit:],
        "events_truncated": len(events) > limit,
    }


# ---------------------------------------------------------------------------- shared: runs into segments


def _segments(
    ms: Sequence[int],
    labels: Sequence[dict[str, tuple[int, str]]],
    rows: Sequence[str],
    window_minutes: int,
    *,
    max_segments: int = 800,
) -> dict[str, list[list[Any]]]:
    """Per row, unbroken runs of minutes with that row's label as [start_ms, end_ms, level, code] (end
    exclusive). ``labels`` holds, per minute, {row: (level, code)} for the rows present in that minute.

    On long windows runs are joined across short breaks (about 1/600 of the window) so a month stays
    readable; a joined run keeps its highest level and its most frequent code.
    """
    join = max(1, window_minutes // 600) * MINUTE_MS
    segs: dict[str, list[list[Any]]] = {r: [] for r in rows}
    codes: dict[str, list[Counter[str]]] = {r: [] for r in rows}
    for t, lab in zip(ms, labels, strict=True):
        for row, (level, code) in lab.items():
            rs = segs[row]
            if rs and t - rs[-1][1] < join:
                last = rs[-1]
                last[1] = t + MINUTE_MS
                if level > last[2]:
                    last[2] = level
                codes[row][-1][code] += 1
            else:
                rs.append([t, t + MINUTE_MS, level, code])
                codes[row].append(Counter({code: 1}))
    for row in rows:
        for seg, c in zip(segs[row], codes[row], strict=True):
            seg[3] = c.most_common(1)[0][0]
        segs[row] = segs[row][:max_segments]
    return segs


# ---------------------------------------------------------------------------- sky condition

COVERS = ("FEW", "SCT", "BKN", "OVC")
CLEAR = frozenset({"NCD", "NSC", "SKC", "CLR", "CAVOK"})
LOW_TOP_FT = 6_500  # WMO bands, agreed 2026-11-05: low < 6,500 ft <= middle < 20,000 ft <= high
MIDDLE_TOP_FT = 20_000
BANDS = ("low", "middle", "high")
_LAYER = re.compile(r"^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?$")
_VV = re.compile(r"^VV(\d{3}|///)$")


def band(height_ft: int) -> str:
    return "low" if height_ft < LOW_TOP_FT else "middle" if height_ft < MIDDLE_TOP_FT else "high"


@lru_cache(maxsize=16_384)
def parse_sky(text: str) -> dict[str, Any]:
    """``"FEW020 BKN060"`` -> layers [(cover, height_ft, type)]; ``VVnnn`` -> sky obscured; ``NCD`` -> clear."""
    layers: list[tuple[str, int, str | None]] = []
    vv: int | None = None
    obscured = clear = False
    for tok in text.split():
        if tok in CLEAR:
            clear = True
        elif m := _LAYER.match(tok):
            layers.append((m.group(1), int(m.group(2)) * 100, m.group(3)))
        elif m := _VV.match(tok):
            obscured = True
            vv = None if m.group(1) == "///" else int(m.group(1)) * 100
    return {"layers": layers, "vv": vv, "obscured": obscured, "clear": clear and not layers and not obscured}


@lru_cache(maxsize=16_384)
def _sky_facts(text: str) -> tuple[bool, bool, tuple[tuple[str, int], ...], tuple[int, str] | None]:
    """(clear, obscured, densest cover index per band, lowest ceiling as (height_ft, cover)) for one string."""
    sky = parse_sky(text)
    top: dict[str, int] = {}
    ceiling: tuple[int, str] | None = None
    for cover, h, _ in sky["layers"]:
        bnd = band(h)
        top[bnd] = max(top.get(bnd, -1), COVERS.index(cover))
        if cover in ("BKN", "OVC") and (ceiling is None or h < ceiling[0]):
            ceiling = (h, cover)
    if sky["obscured"] and sky["vv"] is not None and (ceiling is None or sky["vv"] < ceiling[0]):
        ceiling = (sky["vv"], "VV")
    return sky["clear"], sky["obscured"], tuple(top.items()), ceiling


def sky_summary(ms: Sequence[int], values: Sequence[str | None], window_minutes: int) -> dict[str, Any]:
    """Cloud layers over time (each time bucket's most frequent sky) and the share of time per band."""
    bucket_ms = max(1, math.ceil(window_minutes / 240)) * MINUTE_MS
    first = ms[0] if ms else 0
    buckets: dict[int, Counter[str]] = {}
    first_seen: dict[str, int] = {}
    for t, v in zip(ms, values, strict=True):
        if v is not None:
            buckets.setdefault((t - first) // bucket_ms, Counter())[v] += 1
            first_seen.setdefault(v, t)
    totals: Counter[str] = Counter()
    for c in buckets.values():
        totals.update(c)
    band_minutes = {b: dict.fromkeys(COVERS, 0) for b in BANDS}
    clear = obscured = 0
    ceiling: tuple[int, str, int] | None = None  # (height_ft, cover, time_ms)
    for text, n in totals.items():
        is_clear, is_obscured, tops, ceil = _sky_facts(text.strip())
        clear += n * is_clear
        obscured += n * is_obscured
        for bnd, i in tops:
            band_minutes[bnd][COVERS[i]] += n
        if ceil and (ceiling is None or (ceil[0], first_seen[text]) < (ceiling[0], ceiling[2])):
            ceiling = (ceil[0], ceil[1], first_seen[text])
    timeline = []
    for b in sorted(buckets):
        sky = parse_sky(buckets[b].most_common(1)[0][0].strip())
        timeline.append(
            {
                "t": first + b * bucket_ms,
                "layers": [[c, h, k] for c, h, k in sky["layers"]],
                "vv": sky["vv"],
                "obscured": sky["obscured"],
                "clear": sky["clear"],
            }
        )
    return {
        "bucket_minutes": bucket_ms // MINUTE_MS,
        "bands": {"low_top_ft": LOW_TOP_FT, "middle_top_ft": MIDDLE_TOP_FT},
        "band_minutes": band_minutes,
        "clear_minutes": clear,
        "obscured_minutes": obscured,
        "reported_minutes": sum(totals.values()),
        "lowest_ceiling": {"height_ft": ceiling[0], "cover": ceiling[1], "time": _time(ceiling[2])}
        if ceiling
        else None,
        "timeline": timeline,
    }


# ---------------------------------------------------------------------------- present weather

WEATHER_ROWS = ("thunderstorm", "rain", "drizzle", "mist_fog", "haze", "other")
_PHENOMENA = {
    "RA": "rain",
    "DZ": "drizzle",
    "BR": "mist_fog",
    "FG": "mist_fog",
    "HZ": "haze",
    "FU": "haze",
    "DU": "haze",
    "SA": "haze",
}
_WX_TOKEN = re.compile(r"^([+-]?)(VC)?((?:MI|BC|PR|DR|BL|SH|TS|FZ)*)((?:[A-Z]{2})*)$")


@lru_cache(maxsize=4_096)
def parse_weather(code: str) -> dict[str, int]:
    """METAR present weather -> {row: level}. Levels: 1 light or in the vicinity, 2 moderate, 3 heavy.

    ``-TSRA`` -> thunderstorm 1, rain 1; ``VCTS DZ`` -> thunderstorm 1, drizzle 2; ``BR`` -> mist_fog 2.
    """
    rows: dict[str, int] = {}

    def put(row: str, level: int) -> None:
        rows[row] = max(rows.get(row, 0), level)

    for tok in code.split():
        m = _WX_TOKEN.match(tok)
        if not m:
            put("other", 2)
            continue
        sign, vicinity, descriptors, phen = m.groups()
        level = 1 if sign == "-" else 3 if sign == "+" else 2
        if vicinity:
            level = 1
        if "TS" in descriptors:
            put("thunderstorm", level)
        names = [phen[i : i + 2] for i in range(0, len(phen), 2)]
        for p in names:
            put(_PHENOMENA.get(p, "other"), level)
        if not names and "TS" not in descriptors:
            put("other", level)
    return rows


def weather_summary(ms: Sequence[int], values: Sequence[str | None], window_minutes: int) -> dict[str, Any]:
    """One row per kind of weather with its time segments, minutes per row and the codes seen."""
    labels: list[dict[str, tuple[int, str]]] = []
    for v in values:
        code = v.strip() if v else ""
        labels.append({row: (level, code) for row, level in parse_weather(code).items()} if code else {})
    minutes = Counter(row for lab in labels for row in lab)
    segs = _segments(ms, labels, WEATHER_ROWS, window_minutes)
    return {
        "rows": [{"key": r, "minutes": minutes[r], "segments": segs[r]} for r in WEATHER_ROWS],
        "weather_minutes": sum(1 for lab in labels if lab),
        "reported_minutes": sum(1 for v in values if v is not None),
    }


# ---------------------------------------------------------------------------- lightning

LIGHTNING_ROWS = ("airport", "vicinity", "distant")
DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW", "ALQDS")


@lru_cache(maxsize=4_096)
def parse_lightning(text: str) -> tuple[str | None, tuple[str, ...]]:
    """``"TS in Vicinity - LTG DSNT NE AND E"`` -> ("vicinity", ("NE", "E")). Empty -> (None, ())."""
    up = text.upper()
    level = "airport" if "AT AIRPORT" in up else "vicinity" if "IN VICINITY" in up else None
    dirs: tuple[str, ...] = ()
    if "LTG" in up:
        level = level or "distant"
        tail = up.split("DSNT", 1)[1] if "DSNT" in up else ""
        dirs = tuple(d for d in re.split(r"[\s,]+|\bAND\b", tail) if d in DIRECTIONS)
    return level, dirs


def lightning_summary(ms: Sequence[int], values: Sequence[str | None], window_minutes: int) -> dict[str, Any]:
    """How close the storm was over time, minutes per row, distant lightning by direction, and episodes
    (lightning separated by more than 15 quiet minutes counts as a new episode)."""
    labels: list[dict[str, tuple[int, str]]] = []
    minutes = dict.fromkeys(LIGHTNING_ROWS, 0)
    directions = dict.fromkeys(DIRECTIONS, 0)
    episodes = 0
    last_seen: int | None = None
    first_time = last_time = None
    for t, v in zip(ms, values, strict=True):
        text = v.strip() if v else ""
        level, dirs = parse_lightning(text) if text else (None, ())
        if level is None:
            labels.append({})
            continue
        labels.append({level: (1, text)})
        minutes[level] += 1
        for d in dirs:
            directions[d] += 1
        if last_seen is None or t - last_seen > 15 * MINUTE_MS:
            episodes += 1
        last_seen = t
        first_time = first_time or _time(t)
        last_time = _time(t)
    segs = _segments(ms, labels, LIGHTNING_ROWS, window_minutes)
    return {
        "rows": [{"key": r, "minutes": minutes[r], "segments": segs[r]} for r in LIGHTNING_ROWS],
        "directions": directions,
        "episodes": episodes,
        "first": first_time,
        "last": last_time,
        "reported_minutes": sum(1 for v in values if v is not None),
    }
