"""The report's two charts, drawn as SVG from the same numbers as its tables.

Both are plain lines and bars with the values on a fixed grid, so they print sharply and read in black and white
too: SLA is a solid line with round markers, OLA a dashed line with square markers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from xml.sax.saxutils import escape

from simola.report.texts import Words

INK = "#111722"
INK2 = "#4c5667"
INK3 = "#7b8597"
LINE = "#dde1e7"
EMPTY = "#eef0f3"
SLA = "#1f63d6"
OLA = "#111722"
ERROR = "#df4a40"
WARNING = "#f2b02c"


@dataclass(frozen=True)
class DayPoint:
    day: date
    sla: float | None
    ola: float | None
    state: str  # "ok", "no_coverage" (nothing to count), "future" (the month is still running)


def scale_floor(lowest: float) -> tuple[float, float]:
    """The bottom of the % axis and its tick step: as close to 100 as the lowest value allows."""
    for lo, step in ((99.0, 0.25), (98.0, 0.5), (95.0, 1.0), (90.0, 2.0), (80.0, 5.0), (50.0, 10.0)):
        if lowest >= lo:
            return lo, step
    return 0.0, 20.0


def daily_chart(points: Sequence[DayPoint], good: float, warning: float, w: Words) -> str:
    width, height = 720, 236
    left, right, top, bottom = 46, 704, 12, 196
    n = max(len(points), 1)
    band = (right - left) / n
    values = [v for p in points for v in (p.sla, p.ola) if v is not None]
    lo, step = scale_floor(min([*values, 100.0]))
    digits = 2 if step < 0.5 else 1 if step < 1 else 0

    def x(i: int) -> float:
        return left + band * (i + 0.5)

    def y(v: float) -> float:
        return bottom - (v - lo) / (100.0 - lo) * (bottom - top)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'font-family="Inter" font-size="9" class="chart">'
    ]
    # days without anything to count
    for i, p in enumerate(points):
        if p.state != "ok":
            fill = EMPTY if p.state == "no_coverage" else "#f7f8fa"
            out.append(
                f'<rect x="{left + band * i:.1f}" y="{top}" width="{band:.1f}" height="{bottom - top}" '
                f'fill="{fill}"/>'
            )
    # grid and the % axis
    v = lo
    while v <= 100.0 + 1e-9:
        yy = y(v)
        out.append(
            f'<line x1="{left}" x2="{right}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{LINE}" stroke-width="0.6"/>'
        )
        out.append(
            f'<text x="{left - 6}" y="{yy + 3:.1f}" text-anchor="end" fill="{INK3}">{escape(w.num(v, digits))}</text>'
        )
        v += step
    # the display thresholds (colour levels on the dashboard)
    for t in (good, warning):
        if lo < t < 100:
            yy = y(t)
            out.append(
                f'<line x1="{left}" x2="{right}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{INK3}" '
                f'stroke-width="0.8" stroke-dasharray="2 3"/>'
            )
    # day numbers
    for i, p in enumerate(points):
        out.append(
            f'<text x="{x(i):.1f}" y="{bottom + 13}" text-anchor="middle" fill="{INK2}">{p.day.day}</text>'
        )
    out.append(
        f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{INK3}" stroke-width="0.8"/>'
    )

    def series(get: str, color: str, dash: str, marker: str) -> None:
        runs: list[list[tuple[float, float]]] = [[]]
        for i, p in enumerate(points):
            val = getattr(p, get)
            if val is None or p.state != "ok":
                runs.append([])
                continue
            runs[-1].append((x(i), y(val)))
        for run in runs:
            if len(run) > 1:
                pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in run)
                out.append(
                    f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" '
                    f'stroke-linejoin="round"{dash}/>'
                )
            for a, b in run:
                if marker == "circle":
                    out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.2" fill="{color}"/>')
                else:
                    out.append(f'<rect x="{a - 2:.1f}" y="{b - 2:.1f}" width="4" height="4" fill="{color}"/>')

    series("ola", OLA, ' stroke-dasharray="4 2.5"', "square")
    series("sla", SLA, "", "circle")
    # the lowest SLA day, when it lost anything
    ok = [(i, p) for i, p in enumerate(points) if p.sla is not None and p.state == "ok"]
    if ok:
        i, p = min(ok, key=lambda ip: (ip[1].sla, ip[0]))
        if p.sla is not None and p.sla < 100:
            yy = y(p.sla)
            right_side = x(i) < right - 60
            out.append(
                f'<text x="{x(i) + (6 if right_side else -6):.1f}" y="{min(yy + 3, bottom - 3):.1f}" '
                f'text-anchor="{"start" if right_side else "end"}" font-weight="600" '
                f'fill="{SLA}">{escape(w.pct(p.sla))} %</text>'
            )
    # legend
    lx = left
    ly = height - 10
    for label, color, dash, marker in (
        (w("sla"), SLA, "", "circle"),
        (w("ola"), OLA, ' stroke-dasharray="4 2.5"', "square"),
    ):
        out.append(
            f'<line x1="{lx}" x2="{lx + 22}" y1="{ly - 3}" y2="{ly - 3}" stroke="{color}" stroke-width="1.6"{dash}/>'
        )
        if marker == "circle":
            out.append(f'<circle cx="{lx + 11}" cy="{ly - 3}" r="2.2" fill="{color}"/>')
        else:
            out.append(f'<rect x="{lx + 9}" y="{ly - 5}" width="4" height="4" fill="{color}"/>')
        out.append(f'<text x="{lx + 28}" y="{ly}" fill="{INK}">{escape(label)}</text>')
        lx += 70
    out.append(
        f'<line x1="{lx}" x2="{lx + 22}" y1="{ly - 3}" y2="{ly - 3}" stroke="{INK3}" stroke-width="0.8" '
        f'stroke-dasharray="2 3"/>'
    )
    out.append(
        f'<text x="{lx + 28}" y="{ly}" fill="{INK}">{escape(w.num(good, 0))} % · {escape(w.num(warning, 0))} %</text>'
    )
    lx += 90
    if any(p.state == "no_coverage" for p in points):
        out.append(f'<rect x="{lx}" y="{ly - 8}" width="12" height="9" fill="{EMPTY}" stroke="{LINE}"/>')
        out.append(f'<text x="{lx + 17}" y="{ly}" fill="{INK}">{escape(w("level_none"))}</text>')
    out.append("</svg>")
    return "".join(out)


def nice_max(n: int) -> tuple[int, int]:
    """The top of a count axis and its tick step."""
    if n <= 4:
        return 4, 1
    for step in (2, 5, 10, 20, 50, 100, 200, 500):
        if n <= step * 4:
            return -(-n // step) * step, step
    step = 1000
    return -(-n // step) * step, step


def alarm_chart(per_day: Sequence[tuple[date, int, int]], w: Words) -> str:
    """Alarms raised per UTC day, errors below warnings."""
    width, height = 720, 132
    left, right, top, bottom = 46, 704, 10, 100
    n = max(len(per_day), 1)
    band = (right - left) / n
    peak, step = nice_max(max([e + wn for _, e, wn in per_day] + [0]))

    def y(v: float) -> float:
        return bottom - v / peak * (bottom - top)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'font-family="Inter" font-size="9" class="chart">'
    ]
    for v in range(0, peak + 1, step):
        yy = y(v)
        out.append(
            f'<line x1="{left}" x2="{right}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{LINE}" stroke-width="0.6"/>'
        )
        out.append(
            f'<text x="{left - 6}" y="{yy + 3:.1f}" text-anchor="end" fill="{INK3}">{w.integer(v)}</text>'
        )
    bar = band * 0.62
    for i, (d, err, warn) in enumerate(per_day):
        x0 = left + band * i + (band - bar) / 2
        if err:
            out.append(
                f'<rect x="{x0:.1f}" y="{y(err):.1f}" width="{bar:.1f}" height="{bottom - y(err):.1f}" fill="{ERROR}"/>'
            )
        if warn:
            out.append(
                f'<rect x="{x0:.1f}" y="{y(err + warn):.1f}" width="{bar:.1f}" '
                f'height="{y(err) - y(err + warn):.1f}" fill="{WARNING}"/>'
            )
        out.append(
            f'<text x="{x0 + bar / 2:.1f}" y="{bottom + 12}" text-anchor="middle" fill="{INK2}">{d.day}</text>'
        )
    out.append(
        f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{INK3}" stroke-width="0.8"/>'
    )
    lx, ly = left, height - 4
    for label, color in ((w("type_error"), ERROR), (w("type_warning"), WARNING)):
        out.append(f'<rect x="{lx}" y="{ly - 8}" width="10" height="9" fill="{color}"/>')
        out.append(f'<text x="{lx + 15}" y="{ly}" fill="{INK}">{escape(label)}</text>')
        lx += 90
    out.append("</svg>")
    return "".join(out)
