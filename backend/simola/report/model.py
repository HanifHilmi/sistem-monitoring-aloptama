"""What goes on each page of the monthly report, built from the dashboard's own answers.

``ReportInputs`` holds, for one system and UTC month, exactly what the API returns to the dashboard: ``/kpis``,
``/matrix`` (by day), ``/outages`` (scopes ``ola`` and ``sla``), ``/data-quality``, and the calibration status
from ``/assets``; plus the alarm summary of the month. ``context`` turns them into the words and numbers the
template prints, so a figure in the PDF is the dashboard's figure, only written out (FR-EXP-001).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from simola.kpi.engine import pct
from simola.report.charts import DayPoint, alarm_chart, daily_chart
from simola.report.texts import Lang, Words

CAUSES = ("cdp_no_data", "no_record", "field_missing", "flagged", "detection")
CAL_ORDER = ("overdue", "due_soon", "unknown", "ok")
TOP_OUTAGES = 15
TOP_ALARMS = 10


@dataclass(frozen=True)
class ReportInputs:
    system: Mapping[str, Any]  # GET /systems/{code}
    station: Mapping[str, Any]  # the station record (name, ICAO, airport)
    month: date  # first day of the UTC month
    lang: Lang
    generated_at: datetime
    generated_by: str
    definitions: Mapping[str, Any]  # GET /definitions
    thresholds: Mapping[str, float]  # display thresholds: good, warning
    kpis: Mapping[str, Any]  # GET /kpis for the month
    matrix: Mapping[str, Any]  # GET /matrix?bucket=day for the month
    outages: Mapping[str, Any]  # GET /outages?scope=ola
    sla_outages: Mapping[str, Any]  # GET /outages?scope=sla
    alarms: Mapping[str, Any]  # alarm summary: raised by type, per day, by name
    quality: Mapping[str, Any]  # GET /data-quality (as a signed-in user)
    calibration: Mapping[str, Any]  # as_of, due_soon_days, components [{site, type, calibration}]


def as_datetime(v: datetime | str) -> datetime:
    if isinstance(v, datetime):
        return v.astimezone(UTC)
    return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(UTC)


def as_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v[:10])


def next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def level(p: float | None, lost: int, expected: int | None, good: float, warning: float) -> str:
    """The dashboard's colour level (figureLevel): 'full' only when no minute was lost."""
    if p is None or expected == 0:
        return "none"
    if p >= 100:
        return "good" if lost > 0 else "full"
    if p >= good:
        return "good"
    if p >= warning:
        return "warn"
    return "bad"


class _Builder:
    def __init__(self, r: ReportInputs) -> None:
        self.r = r
        self.w = Words(r.lang)
        self.good = float(r.thresholds["good"])
        self.warning = float(r.thresholds["warning"])
        self.sites = {s["slug"]: s for s in r.system["sites"]}
        self.n_components = sum(len(s["components"]) for s in r.system["sites"])

    # ---- small helpers
    def lv(self, f: Mapping[str, Any], lost: int | None = None) -> str:
        expected = f.get("expected")
        missing = lost if lost is not None else int(f.get("missing") or 0)
        return level(f.get("pct"), missing, expected, self.good, self.warning)

    def site_name(self, slug: str | None) -> str:
        if slug is None or slug not in self.sites:
            return slug or ""
        return str(self.sites[slug]["name"][self.r.lang])

    def component_name(self, slug: str, type_code: str) -> str:
        for c in self.sites.get(slug, {}).get("components", []):
            if c["type"] == type_code:
                return str(c["name"][self.r.lang])
        return type_code

    def figure(self, f: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "pct": self.w.pct(f.get("pct")),
            "level": self.lv(f),
            "valid": self.w.integer(f.get("valid")),
            "expected": self.w.integer(f.get("expected")),
            "lost": self.w.integer(f.get("missing")),
        }

    # ---- cover
    def cover(self) -> dict[str, Any]:
        r, w = self.r, self.w
        last = next_month(r.month) - timedelta(days=1)
        period = r.kpis["period"]
        expected = int(r.kpis["sla"]["expected"])
        start = as_datetime(r.system["coverage_start"])
        days = self.day_states()
        empty = [d for d, s in days if s == "no_coverage"]
        counted = [d for d, s in days if s != "future"]
        if not empty:
            coverage = w("coverage_all")
        elif len(empty) == len(counted):
            coverage = w("coverage_none", start=f"{w.day_long(start.date())} {start:%H:%M} UTC")
        else:
            coverage = w(
                "coverage_some",
                days=w.days_list(empty),
                start=f"{w.day_long(start.date())} {start:%H:%M} UTC",
            )
        station = r.station
        airport = station.get("airport_name") or station["name"][r.lang]
        return {
            "report": w("report"),
            "system": r.system["name"][r.lang],
            "month": w.month(r.month),
            "station": f"{airport} ({station.get('icao') or r.system.get('icao')})",
            "period": w(
                "period_value",
                first=w.day_long(r.month) if r.month.month != last.month else str(r.month.day),
                last=w.day_long(last),
                minutes=w.integer(expected),
            ),
            "generated": f"{w.time(r.generated_at)} UTC",
            "generated_by": r.generated_by,
            "definitions": w(
                "definitions_value", v=r.definitions["version"], source=r.definitions.get("source", "")
            ),
            "coverage": coverage,
            "open": w("open", time=f"{w.time(as_datetime(period['evaluated_to']))} UTC")
            if period.get("open")
            else None,
        }

    def headline(self) -> list[dict[str, Any]]:
        k, w = self.r.kpis, self.w
        ola_lost = sum(int(s["availability"]["missing"]) for s in k["sites"])
        tiles = [
            {"label": w("sla"), **self.figure(k["sla"])},
            {
                "label": w("ola"),
                "pct": w.pct(k["ola"]["pct"]),
                "level": self.lv({"pct": k["ola"]["pct"], "expected": k["pooled"]["expected"]}, ola_lost),
                "lost": None,
            },
            {"label": w("pooled"), **self.figure(k["pooled"])},
        ]
        tiles += [{"label": w("uptime_of", cdp=c["code"]), **self.figure(c["uptime"])} for c in k["cdps"]]
        return tiles

    # ---- 1 KPI summary, 2 sites
    def kpi_rows(self) -> list[dict[str, Any]]:
        k, w = self.r.kpis, self.w
        ola_lost = sum(int(s["availability"]["missing"]) for s in k["sites"])
        rows = [
            {"label": w("sla"), "hint": w("sla_hint"), **self.figure(k["sla"])},
            {
                "label": w("ola"),
                "hint": w("ola_hint"),
                "pct": w.pct(k["ola"]["pct"]),
                "level": self.lv({"pct": k["ola"]["pct"], "expected": k["pooled"]["expected"]}, ola_lost),
                "valid": "",
                "expected": "",
                "lost": w.integer(ola_lost),
            },
            {"label": w("pooled"), "hint": w("pooled_hint"), **self.figure(k["pooled"])},
        ]
        rows += [
            {"label": w("uptime_of", cdp=c["code"]), "hint": w("uptime_hint"), **self.figure(c["uptime"])}
            for c in k["cdps"]
        ]
        return rows

    def reach_rows(self) -> list[dict[str, Any]]:
        w = self.w
        out = []
        for c in self.r.kpis["cdps"]:
            r = c["reachability"]
            out.append(
                {
                    "cdp": c["code"],
                    "pct": w.pct(r["pct"]) if r["sampled"] else w("no_probe"),
                    "probed": w.integer(r["sampled"]),
                    "coverage": w.pct(r["probe_coverage_pct"]),
                }
            )
        return out

    def site_groups(self) -> list[dict[str, Any]]:
        out = []
        for s in self.r.kpis["sites"]:
            slug = s["slug"]
            out.append(
                {
                    "name": self.site_name(slug),
                    **self.figure(s["availability"]),
                    "components": [
                        {
                            "type": c["type"],
                            "name": self.component_name(slug, c["type"]),
                            **self.figure(c["availability"]),
                        }
                        for c in s["components"]
                    ],
                }
            )
        return out

    # ---- 3 day by day
    def day_states(self) -> list[tuple[date, str]]:
        m = self.r.matrix
        evaluated_to = as_datetime(m["period"]["evaluated_to"])
        sla = next(row for row in m["rows"] if row["kind"] == "sla")
        out = []
        for b, cell in zip(m["buckets"], sla["cells"], strict=True):
            d = as_date(b["start"])
            assert d is not None
            if cell.get("expected"):
                out.append((d, "ok"))
            elif datetime(d.year, d.month, d.day, tzinfo=UTC) >= evaluated_to:
                out.append((d, "future"))
            else:
                out.append((d, "no_coverage"))
        return out

    def days(self) -> dict[str, Any]:
        m, w = self.r.matrix, self.w
        rows = {row["key"]: row for row in m["rows"]}
        sla = rows["sla"]
        ola = rows["ola"]
        cdps = [row for row in m["rows"] if row["kind"] == "cdp"]
        sites = [row for row in m["rows"] if row["kind"] == "site"]
        states = self.day_states()
        points: list[DayPoint] = []
        table = []
        for i, (d, state) in enumerate(states):
            ola_lost = sum(int(s["cells"][i].get("missing") or 0) for s in sites)
            points.append(DayPoint(d, sla["cells"][i]["pct"], ola["cells"][i]["pct"], state))
            note = None if state == "ok" else w("no_coverage") if state == "no_coverage" else w("not_yet")
            table.append(
                {
                    "date": w.day_short(d),
                    "note": note,
                    "sla": w.pct(sla["cells"][i]["pct"]),
                    "sla_level": self.lv(sla["cells"][i]),
                    "ola": w.pct(ola["cells"][i]["pct"]),
                    "ola_level": self.lv(
                        {"pct": ola["cells"][i]["pct"], "expected": sla["cells"][i].get("expected")}, ola_lost
                    ),
                    "cdps": [
                        {"pct": w.pct(c["cells"][i]["pct"]), "level": self.lv(c["cells"][i])} for c in cdps
                    ],
                    "lost": w.integer(sla["cells"][i].get("missing")) if state == "ok" else "",
                }
            )
        half = (len(table) + 1) // 2
        return {
            "chart": daily_chart(points, self.good, self.warning, w),
            "cdp_codes": [c["cdp"] for c in cdps],
            # two days a line: 1 and 17 October side by side, and so on
            "pairs": [(table[i], table[i + half] if i + half < len(table) else None) for i in range(half)],
            "matrix": self.matrix(states),
        }

    def matrix(self, states: list[tuple[date, str]]) -> dict[str, Any]:
        m, w = self.r.matrix, self.w
        sites = [row for row in m["rows"] if row["kind"] == "site"]
        rows = []
        for row in m["rows"]:
            kind = row["kind"]
            if kind == "sla":
                label = w("sla")
            elif kind == "cdp":
                label = w("uptime_of", cdp=row["cdp"])
            elif kind == "ola":
                label = w("ola")
            elif kind == "site":
                label = self.site_name(row["site"])
            else:
                label = row["type"]
            cells = []
            for i, cell in enumerate(row["cells"]):
                if states[i][1] != "ok":
                    cells.append("none" if states[i][1] == "no_coverage" else "future")
                elif kind == "ola":
                    lost = sum(int(s["cells"][i].get("missing") or 0) for s in sites)
                    cells.append(self.lv({"pct": cell["pct"], "expected": 1}, lost))
                else:
                    cells.append(self.lv(cell))
            total = row["total"]
            if kind == "ola":
                lost = sum(int(s["total"].get("missing") or 0) for s in sites)
                total_level = self.lv({"pct": total["pct"], "expected": 1}, lost)
            else:
                total_level = self.lv(total)
            rows.append(
                {
                    "label": label,
                    "kind": kind,
                    "cells": cells,
                    "total": w.pct(total["pct"]),
                    "total_level": total_level,
                }
            )
        return {
            "days": [d.day for d, _ in states],
            "rows": rows,
            "legend": [
                ("full", w("level_full")),
                ("good", w("level_good", good=w.pct(self.good))),
                ("warn", w("level_warn", good=w.pct(self.good), warning=w.pct(self.warning))),
                ("bad", w("level_bad", warning=w.pct(self.warning))),
                ("none", w("level_none")),
            ],
        }

    # ---- 4 outages
    def where(self, comps: list[Mapping[str, Any]]) -> str:
        if not comps:
            return ""
        if len(comps) == self.n_components:
            return self.w("all_components", n=len(comps))
        by_site: dict[str, list[str]] = {}
        for c in comps:
            by_site.setdefault(c["site"], []).append(c["component"])
        order = list(self.sites)
        return "; ".join(
            f"{self.site_name(s)}: {', '.join(by_site[s])}"
            for s in sorted(by_site, key=lambda s: order.index(s) if s in order else 99)
        )

    def detail(self, o: Mapping[str, Any]) -> str:
        w = self.w
        if o["cause"] == "flagged" and o.get("flags"):
            return w(f"reason_{o['flags'][0]['reason']}")
        if o["cause"] == "detection" and o.get("detections"):
            d = o["detections"][0]
            return f"{w('rule_' + d['type'])} · {d['field']}"
        if o["cause"] == "field_missing":
            fields: list[str] = []
            for c in o.get("components", []):
                fields += [f for f in c.get("fields", []) if f not in fields]
            return ", ".join(fields)
        return ""

    def outages(self) -> dict[str, Any]:
        o, sla, w = self.r.outages, self.r.sla_outages, self.w
        total = sum(int(v) for v in o["by_cause"].values())
        n = int(o["intervals_total"])
        rows = []
        for i, x in enumerate(o["intervals"][:TOP_OUTAGES]):
            rows.append(
                {
                    "n": i + 1,
                    "start": w.time(as_datetime(x["start"])),
                    "end": w("ongoing") if x.get("ongoing") else w.time(as_datetime(x["end"])),
                    "duration": w.duration(int(x["minutes"])),
                    "cause": x["cause"],
                    "cause_label": w(f"cause_{x['cause']}"),
                    "where": self.where(x.get("components", [])),
                    "detail": self.detail(x),
                }
            )
        causes = [
            {
                "key": c,
                "label": w(f"cause_{c}"),
                "minutes": w.integer(int(o["by_cause"].get(c, 0))),
                "share": int(o["by_cause"].get(c, 0)) / total * 100 if total else 0,
            }
            for c in CAUSES
            if int(o["by_cause"].get(c, 0))
        ]
        sla_lost = int(sla["availability"]["missing"])
        if sla_lost and sla["intervals"]:
            first = sla["intervals"][0]
            sla_line = w(
                "sla_outages",
                int(sla["intervals_total"]),
                minutes=w.integer(sla_lost),
                n=w.integer(int(sla["intervals_total"])),
                dur=w.duration(int(first["minutes"])),
                start=f"{w.time(as_datetime(first['start']))} UTC",
            )
        else:
            sla_line = w("sla_none")
        return {
            "intro": w("outages_intro", n, minutes=w.integer(total), n=w.integer(n))
            if total
            else w("outages_none"),
            "list": w("outages_list", k=len(rows)) if rows else None,
            "sla": sla_line,
            "causes": causes,
            "rows": rows,
        }

    # ---- 5 alarms
    def place(self, p: Mapping[str, Any]) -> str:
        kind = p.get("kind")
        if kind == "station":
            return self.w("place_station")
        if kind == "unmapped" or kind is None:
            return self.w("place_unmapped")
        if kind == "component":
            return f"{self.site_name(p.get('site'))} · {p.get('component')}"
        return self.site_name(p.get("site"))

    def alarms(self) -> dict[str, Any]:
        a, w = self.r.alarms, self.w
        per_day = [(as_date(d["day"]), int(d["error"]), int(d["warning"])) for d in a["per_day"]]
        raised = int(a["raised"].get("error", 0)) + int(a["raised"].get("warning", 0))
        names = sorted(a["names"], key=lambda n: (-int(n["raised"]), n["name"]))[:TOP_ALARMS]
        return {
            "tiles": [
                (w("raised_error"), w.integer(int(a["raised"].get("error", 0))), "error"),
                (w("raised_warning"), w.integer(int(a["raised"].get("warning", 0))), "warning"),
                (w("changes"), w.integer(int(a["changes"])), ""),
                (w("names"), w.integer(int(a["names_total"])), ""),
            ],
            "chart": alarm_chart([(d, e, x) for d, e, x in per_day if d is not None], w) if raised else None,
            "rows": [
                {
                    "name": n["name"],
                    "type": n["type"],
                    "type_label": w(f"type_{n['type']}"),
                    "place": self.place(n["place"]),
                    "raised": w.integer(int(n["raised"])),
                    "last": w.time(as_datetime(n["last"])) if n.get("last") else "—",
                }
                for n in names
            ],
            "none": None if raised else w("alarms_none"),
        }

    # ---- 6 data quality
    def quality(self) -> dict[str, Any]:
        q, w = self.r.quality, self.w
        rows = []
        for c in q["components"]:
            lost = int(c["flagged_minutes"]) + int(c["detection_minutes"])
            reasons = ", ".join(
                f"{w(('reason_' if x['kind'] == 'flag' else 'rule_') + x['reason'])} "
                f"{w('minutes_short', m=w.integer(int(x['minutes'])))}"
                for x in c["reasons"]
            )
            rows.append(
                {
                    "sensor": f"{self.site_name(c['site'])} · {c['component']}",
                    "flagged": w.integer(int(c["flagged_minutes"])),
                    "flags": int(c["flags"]),
                    "detected": w.integer(int(c["detection_minutes"])),
                    "detections": int(c["detections"]),
                    "share": w.pct(pct(lost, int(c["expected"]))),
                    "reasons": reasons,
                }
            )

        def by(kind: str, prefix: str) -> list[tuple[str, str, str]]:
            return [
                (
                    w(prefix + x["reason"]),
                    w("minutes_short", m=w.integer(int(x["minutes"]))),
                    w(
                        "n_flags" if kind == "flag" else "n_detections",
                        int(x["count"]),
                        n=w.integer(int(x["count"])),
                    ),
                )
                for x in q["reasons"]
                if x["kind"] == kind
            ]

        flags, detections = int(q["flags"]), int(q["detections"])
        return {
            "totals": [
                (
                    w("flagged"),
                    w("minutes_short", m=w.integer(int(q["flagged_minutes"]))),
                    w("n_flags", flags, n=w.integer(flags)),
                    "flag",
                ),
                (
                    w("detected"),
                    w("minutes_short", m=w.integer(int(q["detection_minutes"]))),
                    w("n_detections", detections, n=w.integer(detections)),
                    "detect",
                ),
            ],
            "suspects": None if q.get("pending_suspects") is None else w.integer(int(q["pending_suspects"])),
            "rows": rows,
            "flag_reasons": by("flag", "reason_"),
            "rules": by("detection", "rule_"),
            "none": None if rows else w("quality_none"),
        }

    # ---- 7 calibration
    def calibration(self) -> dict[str, Any]:
        c, w = self.r.calibration, self.w
        as_of = as_date(c["as_of"])
        assert as_of is not None
        rows = []
        counts = dict.fromkeys(CAL_ORDER, 0)
        for x in c["components"]:
            if x["type"] == "DCP":
                continue
            cal = x["calibration"]
            status = cal["status"]
            counts[status] += 1
            left = cal.get("days_left")
            validated = as_date(cal.get("validated_on"))
            last = as_date(cal.get("last"))
            next_due = as_date(cal.get("next_due"))
            rows.append(
                {
                    "site": self.site_name(x["site"]),
                    "type": x["type"],
                    "name": self.component_name(x["site"], x["type"]),
                    "last": w.iso_day(last) if last else "—",
                    "next_due": w.iso_day(next_due) if next_due else "—",
                    "status": status,
                    "status_label": w(f"cal_{status}"),
                    "days": w.integer(left) if left is not None else "—",
                    "certificate": w("validated", date=w.iso_day(validated))
                    if validated
                    else w("pending")
                    if last
                    else "—",
                }
            )
        return {
            "intro": w("calibration_intro", date=w.day_long(as_of), n=w.integer(int(c["due_soon_days"]))),
            "counts": [(s, w(f"cal_{s}"), counts[s]) for s in CAL_ORDER],
            "rows": rows,
        }

    # ---- 8 definitions
    def definitions(self) -> dict[str, Any]:
        d, w = self.r.definitions, self.w
        effective = as_date(d.get("effective_from"))
        return {
            "version": w(
                "definitions_version",
                v=d["version"],
                date=w.day_long(effective) if effective else "—",
                source=d.get("source", ""),
            ),
            "items": [
                (w("sla"), w("def_sla")),
                (w("name_uptime"), w("def_uptime")),
                (w("reach"), w("def_reach")),
                (w("name_component"), w("def_component")),
                (w("name_site"), w("def_site")),
                (w("ola"), w("def_ola")),
                (w("pooled"), w("def_pooled")),
            ],
            "note": w("def_note"),
        }


def context(r: ReportInputs) -> dict[str, Any]:
    """Everything the template prints, in the report's language."""
    b = _Builder(r)
    w = b.w
    sections = [
        ("kpi", w("s_kpi")),
        ("sites", w("s_sites")),
        ("days", w("s_days")),
        ("outages", w("s_outages")),
        ("alarms", w("s_alarms")),
        ("quality", w("s_quality")),
        ("calibration", w("s_calibration")),
        ("definitions", w("s_definitions")),
    ]
    return {
        "lang": r.lang,
        "w": w,
        "sections": sections,
        "cover": b.cover(),
        "headline": b.headline(),
        "kpi_rows": b.kpi_rows(),
        "reach_rows": b.reach_rows(),
        "site_groups": b.site_groups(),
        "days": b.days(),
        "outages": b.outages(),
        "alarms": b.alarms(),
        "quality": b.quality(),
        "calibration": b.calibration(),
        "definitions": b.definitions(),
        "footer": {
            "left": f"SIMOLA · {r.system['name'][r.lang]} · {w.month(r.month)}",
            "right": f"{w('generated')} {w.time(r.generated_at)} UTC · {w('definitions')} {r.definitions['version']}",
        },
    }


def file_name(system_code: str, month: date, lang: Lang) -> str:
    """SIMOLA_<system>_<YYYY-MM>_<lang>.pdf (FR-EXP-001)."""
    return f"SIMOLA_{system_code}_{month:%Y-%m}_{lang}.pdf"
