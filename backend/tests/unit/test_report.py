"""Monthly PDF report (R3.5, FR-EXP-001): words, numbers, pages. The database side is in
tests/integration/test_report.py (every figure equals the dashboard's)."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from simola.report import render
from simola.report.model import ReportInputs, context, file_name, level
from simola.report.texts import LANGS, TEXTS, Words

FRONTEND_I18N = Path(__file__).resolve().parents[3] / "frontend" / "src" / "i18n"
NOV = date(2026, 11, 1)
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------- words and numbers
def test_numbers_follow_the_language_as_on_the_dashboard() -> None:
    en, id_ = Words("en"), Words("id")
    assert (en.integer(44640), id_.integer(44640)) == ("44,640", "44.640")
    assert (en.integer(-27), id_.integer(-1234)) == ("−27", "−1.234")  # a real minus sign
    assert (en.pct(99.84), id_.pct(99.84), en.pct(100.0), en.pct(None)) == ("99.84", "99,84", "100.00", "—")
    assert id_.pct(1234.5) == "1.234,50"
    assert (en.month(NOV), id_.month(NOV)) == ("November 2026", "November 2026")
    assert (en.day_long(date(2026, 10, 1)), id_.day_long(date(2026, 10, 1))) == (
        "1 October 2026",
        "1 Oktober 2026",
    )
    assert Words.time(datetime(2026, 10, 12, 10, 38, 41, tzinfo=UTC)) == "2026-10-12 10:38"


def test_durations_read_like_the_outage_list() -> None:
    en, id_ = Words("en"), Words("id")
    assert [en.duration(m) for m in (7, 41, 120, 150, 1440 + 125)] == [
        "7 min",
        "41 min",
        "2 h",
        "2 h 30 min",
        "1 d 2 h",
    ]
    assert [id_.duration(m) for m in (7, 120, 150)] == ["7 mnt", "2 j", "2 j 30 mnt"]


def test_runs_of_days_are_joined() -> None:
    en = Words("en")
    days = [date(2025, 12, d) for d in (1, 2, 3, 5, 9, 10)]
    assert en.days_list(days) == "1–3 Dec, 5 Dec, 9–10 Dec"
    assert en.days_list([date(2025, 11, 30), date(2025, 12, 1)]) == "30 Nov – 1 Dec"


def test_plurals_in_english_only() -> None:
    assert (Words("en")("n_flags", 1, n="1"), Words("en")("n_flags", 3, n="3")) == ("1 flag", "3 flags")
    assert Words("id")("n_flags", 3, n="3") == "3 penandaan"


def test_both_languages_have_every_word() -> None:
    assert set(TEXTS["en"]) == set(TEXTS["id"])
    for lang in LANGS:
        for key, entry in TEXTS[lang].items():
            assert entry, (lang, key)


def _frontend(lang: str, key: str) -> str:
    node: Any = json.loads((FRONTEND_I18N / f"{lang}.json").read_text(encoding="utf-8"))
    for part in key.split("."):
        node = node[part]
    return str(node)


# The report says these things the way the dashboard says them (frontend/src/i18n).
SAME_AS_DASHBOARD = {
    "sla_hint": "kpi.slaHint",
    "ola_hint": "kpi.olaHint",
    "pooled": "kpi.pooled",
    "pooled_hint": "kpi.pooledHint",
    "uptime_of": "kpi.uptimeOf",
    "uptime_hint": "kpi.uptimeHint",
    "level_full": "board.levelFull",
    **{
        f"cause_{c}": f"outages.cause.{c}"
        for c in ("cdp_no_data", "no_record", "field_missing", "flagged", "detection")
    },
    **{
        f"reason_{r}": f"flags.reason.{r}"
        for r in ("sensor_fault", "maintenance", "calibration", "environmental", "other")
    },
    **{f"rule_{r}": f"rules.type.{r}" for r in ("range", "stuck", "spike")},
    **{f"cal_{s}": f"calibration.status.{s}" for s in ("overdue", "due_soon", "ok", "unknown")},
    "type_error": "alarms.type.error",
    "type_warning": "alarms.type.warning",
    "place_station": "alarms.place.station",
    "place_unmapped": "alarms.place.unmapped",
    "s_alarms": "alarms.title",
    "per_day": "alarms.perDay",
    "s_quality": "quality.title",
    "quality_intro": "quality.subtitle",
    "flagged": "quality.flagged",
    "detected": "quality.detected",
    "suspects": "quality.suspects",
    "suspects_note": "quality.suspectsNote",
    "by_flag_reason": "quality.byFlagReason",
    "by_rule": "quality.byRule",
    "quality_none": "quality.none",
    "quality_note": "quality.note",
    "dcp_note": "calibration.dcp",
    "s_definitions": "definitions.title",
    "reach": "definitions.kpi.reach.name",
    "name_uptime": "definitions.kpi.uptime.name",
    "name_component": "definitions.kpi.component.name",
    "name_site": "definitions.kpi.site.name",
    **{
        f"def_{k}": f"definitions.kpi.{k}.formula"
        for k in ("sla", "uptime", "reach", "component", "site", "ola", "pooled")
    },
}


@pytest.mark.skipif(not FRONTEND_I18N.is_dir(), reason="needs the whole repository")
@pytest.mark.parametrize("lang", LANGS)
def test_the_report_uses_the_dashboards_words(lang: str) -> None:
    differ = {
        key: (TEXTS[lang][key], _frontend(lang, front))
        for key, front in SAME_AS_DASHBOARD.items()
        if TEXTS[lang][key] != _frontend(lang, front)
    }
    assert differ == {}


def test_levels_are_the_dashboards() -> None:
    assert level(100.0, 0, 1440, 99, 95) == "full"
    assert level(100.0, 1, 44640, 99, 95) == "good"  # rounds to 100.00 but lost a minute
    assert level(99.0, 5, 1440, 99, 95) == "good"
    assert level(97.15, 41, 1440, 99, 95) == "warn"
    assert level(94.99, 72, 1440, 99, 95) == "bad"
    assert level(None, 0, 0, 99, 95) == "none"


def test_file_name() -> None:
    assert file_name("WIDN-CAT3", date(2026, 10, 1), "id") == "SIMOLA_WIDN-CAT3_2026-10_id.pdf"


# ---------------------------------------------------------------------------- a month on paper
def _fig(valid: int, expected: int) -> dict[str, Any]:
    pct = None if not expected else round(valid / expected * 100, 2)
    return {"valid": valid, "expected": expected, "missing": expected - valid, "pct": pct}


def _inputs(lang: str = "en") -> ReportInputs:
    """November 2026 on 10 November: no data on 1–2 Nov, 3–10 Nov counted, the rest still to come."""
    comps = {"04": ("DCP", "ATRH"), "middle": ("DCP", "BARO")}
    system = {
        "code": "WIDN-CAT3",
        "name": {"en": "AWOS CAT.III WIDN", "id": "AWOS CAT.III WIDN"},
        "icao": "WIDN",
        "coverage_start": "2026-11-03T00:00:00Z",
        "cdps": [{"code": "CDP1"}, {"code": "CDP2"}],
        "sites": [
            {
                "slug": slug,
                "code": f"RWY{slug.upper()[:3]}",
                "name": {"en": f"Runway {slug}", "id": f"Runway {slug}"},
                "components": [{"type": t, "name": {"en": f"{t} name", "id": f"{t} nama"}} for t in types],
            }
            for slug, types in comps.items()
        ],
    }
    days = [date(2026, 11, d) for d in range(1, 31)]

    def cell(d: date, lost: int = 0) -> dict[str, Any]:
        if d < date(2026, 11, 3) or d > date(2026, 11, 10):
            return {"valid": 0, "expected": 0, "missing": 0, "pct": None}
        expected = 720 if d == date(2026, 11, 10) else 1440
        return _fig(expected - lost, expected)

    def row(key: str, kind: str, lost: dict[int, int] | None = None, **meta: Any) -> dict[str, Any]:
        cells = [cell(d, (lost or {}).get(d.day, 0)) for d in days]
        v = sum(c["valid"] for c in cells)
        e = sum(c["expected"] for c in cells)
        return {"key": key, "kind": kind, **meta, "cells": cells, "total": _fig(v, e)}

    rows = [
        row("sla", "sla", {5: 41}),
        row("cdp:CDP1", "cdp", {5: 41, 6: 3}, cdp="CDP1"),
        row("cdp:CDP2", "cdp", {5: 41}, cdp="CDP2"),
        {
            "key": "ola",
            "kind": "ola",
            "cells": [{"pct": cell(d)["pct"]} for d in days],
            "total": {"pct": 99.5},
        },
    ]
    for slug, types in comps.items():
        rows.append(row(f"site:{slug}", "site", {5: 82}, site=slug))
        rows += [row(f"component:{slug}:{t}", "component", {5: 41}, site=slug, type=t) for t in types]
    sla = rows[0]["total"]
    kpis = {
        "period": {"evaluated_to": "2026-11-10T12:00:00Z", "open": True},
        "sla": sla,
        "cdps": [
            {
                "code": c,
                "uptime": _fig(sla["expected"] - 44, sla["expected"]),
                "reachability": {
                    "reachable": 100,
                    "sampled": 0 if c == "CDP2" else 100,
                    "pct": 100.0,
                    "probe_coverage_pct": 0.9,
                },
            }
            for c in ("CDP1", "CDP2")
        ],
        "sites": [
            {
                "slug": slug,
                "availability": _fig(2 * sla["expected"] - 82, 2 * sla["expected"]),
                "components": [
                    {"type": t, "availability": _fig(sla["expected"] - 41, sla["expected"])} for t in types
                ],
            }
            for slug, types in comps.items()
        ],
        "ola": {"pct": 99.65},
        "pooled": _fig(4 * sla["expected"] - 164, 4 * sla["expected"]),
    }
    every = [{"site": s, "component": t} for s, types in comps.items() for t in types]
    outages = {
        "by_cause": {"cdp_no_data": 164, "no_record": 0, "field_missing": 20, "flagged": 30, "detection": 0},
        "intervals_total": 4,
        "intervals": [
            {
                "start": "2026-11-05T10:38:00Z",
                "end": "2026-11-05T11:19:00Z",
                "minutes": 41,
                "cause": "cdp_no_data",
                "components": every,
            },
            {
                "start": "2026-11-06T01:00:00Z",
                "end": "2026-11-06T01:30:00Z",
                "minutes": 30,
                "cause": "flagged",
                "components": [every[1]],
                "flags": [{"id": 1, "reason": "maintenance"}],
            },
            {
                "start": "2026-11-07T02:00:00Z",
                "end": "2026-11-07T02:20:00Z",
                "minutes": 20,
                "cause": "field_missing",
                "components": [{**every[1], "fields": ["RH", "TEMP"]}, {**every[3], "fields": ["QNH"]}],
            },
            {
                "start": "2026-11-10T11:50:00Z",
                "end": "2026-11-10T12:00:00Z",
                "minutes": 10,
                "cause": "detection",
                "ongoing": True,
                "components": [every[3]],
                "detections": [{"id": 2, "field": "QNH", "type": "stuck"}],
            },
        ],
    }
    sla_outages = {"availability": sla, "intervals_total": 1, "intervals": [outages["intervals"][0]]}
    alarms = {
        "changes": 9,
        "raised": {"error": 3, "warning": 2},
        "per_day": [
            {
                "day": d.isoformat(),
                "error": 1 if d.day in (4, 5, 6) else 0,
                "warning": 1 if d.day in (7, 8) else 0,
            }
            for d in days
        ],
        "names": [
            {
                "name": "BPOutOfRangeWarning",
                "type": "warning",
                "place": {"kind": "station"},
                "raised": 2,
                "last": "2026-11-08T03:00:00Z",
            },
            {
                "name": "<b>DCPA_Missing</b>",
                "type": "error",
                "place": {"kind": "component", "site": "04", "component": "DCP"},
                "raised": 3,
                "last": "2026-11-06T10:43:12Z",
            },
        ],
        "names_total": 2,
    }
    quality = {
        "flagged_minutes": 30,
        "flags": 1,
        "detection_minutes": 10,
        "detections": 1,
        "pending_suspects": 2,
        "components": [
            {
                "site": "04",
                "component": "ATRH",
                "flagged_minutes": 30,
                "flags": 1,
                "detection_minutes": 0,
                "detections": 0,
                "expected": 10800,
                "reasons": [{"kind": "flag", "reason": "maintenance", "minutes": 30, "count": 1}],
            },
            {
                "site": "middle",
                "component": "BARO",
                "flagged_minutes": 0,
                "flags": 0,
                "detection_minutes": 10,
                "detections": 1,
                "expected": 10800,
                "reasons": [{"kind": "detection", "reason": "stuck", "minutes": 10, "count": 1}],
            },
        ],
        "reasons": [
            {"kind": "flag", "reason": "maintenance", "minutes": 30, "count": 1},
            {"kind": "detection", "reason": "stuck", "minutes": 10, "count": 1},
        ],
    }

    def cal(status: str, left: int | None, last: str | None, validated: str | None) -> dict[str, Any]:
        return {
            "status": status,
            "days_left": left,
            "last": last,
            "next_due": "2026-11-07" if last else None,
            "validated_on": validated,
        }

    calibration = {
        "as_of": date(2026, 11, 10),
        "due_soon_days": 30,
        "components": [
            {"site": "04", "type": "DCP", "calibration": cal("unknown", None, None, None)},
            {"site": "04", "type": "ATRH", "calibration": cal("overdue", -3, "2025-11-07", "2025-11-09")},
            {"site": "middle", "type": "DCP", "calibration": cal("unknown", None, None, None)},
            {"site": "middle", "type": "BARO", "calibration": cal("due_soon", 12, "2025-11-22", None)},
        ],
    }
    return ReportInputs(
        system=system,
        station={"name": {"en": "AWOS", "id": "AWOS"}, "icao": "WIDN", "airport_name": 'Airport "A" & <B>'},
        month=NOV,
        lang=lang,  # type: ignore[arg-type]
        generated_at=NOW,
        generated_by="Siti Rahmawati",
        definitions={"version": "1.0", "effective_from": "2025-12-24", "source": "PRD v1.1 §7.3.1"},
        thresholds={"good": 99, "warning": 95},
        kpis=kpis,
        matrix={
            "period": {"evaluated_to": "2026-11-10T12:00:00Z"},
            "buckets": [{"start": d.isoformat()} for d in days],
            "rows": rows,
        },
        outages=outages,
        sla_outages=sla_outages,
        alarms=alarms,
        quality=quality,
        calibration=calibration,
    )


def test_days_without_coverage_are_named_and_days_to_come_are_left_empty() -> None:
    ctx = context(_inputs())
    assert (
        ctx["cover"]["coverage"]
        == "No data coverage on 1–2 Nov: the data starts on 3 November 2026 00:00 UTC."
    )
    assert ctx["cover"]["open"] == "The month is still running: the figures count up to 2026-11-10 12:00 UTC."
    sla = ctx["days"]["matrix"]["rows"][0]
    assert sla["cells"][:2] == ["none", "none"] and sla["cells"][2] == "full" and sla["cells"][4] == "warn"
    assert set(sla["cells"][10:]) == {"future"}
    first, _ = ctx["days"]["pairs"][0]
    assert first["note"] == "no data coverage"
    _, later = ctx["days"]["pairs"][14]
    assert later["date"] == "30 Nov" and later["note"] == "not yet"
    assert Words("id")("no_coverage") in str(context(_inputs("id"))["days"]["pairs"][0][0]["note"])


def test_the_kpi_page_and_the_cover_show_the_dashboard_figures() -> None:
    ctx = context(_inputs("id"))
    sla = ctx["kpi_rows"][0]
    assert (sla["pct"], sla["valid"], sla["expected"], sla["lost"]) == ("99,62", "10.759", "10.800", "41")
    ola = ctx["kpi_rows"][1]
    assert (ola["pct"], ola["valid"], ola["lost"]) == ("99,65", "", "164")  # OLA: the sites' lost minutes
    assert [t["label"] for t in ctx["headline"]] == [
        "SLA",
        "OLA",
        "Semua komponen",
        "Uptime CDP1",
        "Uptime CDP2",
    ]
    assert ctx["reach_rows"][1]["pct"] == "belum diuji"
    assert ctx["cover"]["period"] == "1–30 November 2026 (UTC); 10.800 menit dihitung"


def test_outages_say_where_and_why() -> None:
    o = context(_inputs())["outages"]
    assert o["intro"] == "214 component-minutes lost in 4 intervals across all sites."
    assert (
        o["sla"]
        == "System (SLA): 41 min lost in 1 interval; the longest, 41 min, began 2026-11-05 10:38 UTC."
    )
    assert [c["key"] for c in o["causes"]] == ["cdp_no_data", "field_missing", "flagged"]
    rows = o["rows"]
    assert rows[0]["where"] == "all 4 components"
    assert (rows[1]["where"], rows[1]["detail"]) == ("Runway 04: ATRH", "Maintenance")
    assert (rows[2]["where"], rows[2]["detail"]) == ("Runway 04: ATRH; Runway middle: BARO", "RH, TEMP, QNH")
    assert (rows[3]["end"], rows[3]["detail"]) == ("still running", "Stuck · QNH")


def test_alarms_most_raised_first_and_calibration_without_the_dcp() -> None:
    ctx = context(_inputs())
    assert [r["raised"] for r in ctx["alarms"]["rows"]] == ["3", "2"]
    assert ctx["alarms"]["rows"][0]["place"] == "Runway 04 · DCP"
    assert ctx["alarms"]["rows"][1]["place"] == "Station"
    cal = ctx["calibration"]
    assert [(r["type"], r["days"], r["certificate"]) for r in cal["rows"]] == [
        ("ATRH", "−3", "validated 2025-11-09"),
        ("BARO", "12", "pending"),
    ]
    assert dict((k, n) for k, _, n in cal["counts"]) == {"overdue": 1, "due_soon": 1, "unknown": 0, "ok": 0}
    q = ctx["quality"]
    assert [r["share"] for r in q["rows"]] == ["0.28", "0.09"]
    assert q["suspects"] == "2"


def test_text_from_the_data_is_escaped() -> None:
    html = render.render_html(_inputs())
    assert "<b>DCPA_Missing</b>" not in html and "&lt;b&gt;DCPA_Missing&lt;/b&gt;" in html
    assert "Airport &#34;A&#34; &amp; &lt;B&gt;" in html
    assert html.count("<svg") == 2  # the daily chart and the alarms chart


def test_page_furniture_cannot_leave_its_css_string() -> None:
    s = render.css_string('a"b\\c</style><script>')
    assert s.startswith('"') and s.endswith('"') and s.count('"') == 2
    assert "<" not in s and "\\" + "3c " in s


def test_only_the_bundled_fonts_can_be_loaded() -> None:
    font = render.FONTS / "Inter-Regular.otf"
    assert render.bundled_path(font.as_uri()) == font
    for url in (
        "ftp://example.invalid/Inter-Regular.otf",
        "https://example.invalid/Inter-Regular.otf",
        (render.FONTS / ".." / "templates" / "report.css").as_uri(),
        (render.FONTS / ".." / "fonts" / ".." / "render.py").as_uri(),
        "file:///etc/passwd",
        "data:font/otf;base64,AAAA",
    ):
        assert render.bundled_path(url) is None, url
    assert sorted(p.name for p in render.FONTS.glob("*.otf")) == [
        "Inter-Bold.otf",
        "Inter-Medium.otf",
        "Inter-Regular.otf",
        "Inter-SemiBold.otf",
    ]
    assert (render.FONTS / "OFL.txt").is_file()


def _weasyprint() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False
    return True


@pytest.mark.skipif(
    not _weasyprint() and not os.environ.get("CI"), reason="Pango is not installed (CI installs it)"
)
@pytest.mark.parametrize("lang", LANGS)
def test_a_month_becomes_a_pdf(lang: str) -> None:
    pdf = render.render_pdf(_inputs(lang))
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert render.selftest() > 0
