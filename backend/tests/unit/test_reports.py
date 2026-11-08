"""AWOS report logs (R3.2, FR-ING-009): reading METAR, MET REPORT and TAF logs and merging the two CDPs' copies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from simola import reports
from tests.conftest import fixture_text

CDP1, CDP2 = 1, 2
PREF = {CDP1: 1, CDP2: 2}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


# ------------------------------------------------------------------------------------------ real files
def test_a_metar_log_keeps_the_report_and_the_awos_notes_apart() -> None:
    parsed = reports.parse_text(fixture_text("cdp1_METAR.20261101.log"), "metar")
    assert parsed.warnings == 0
    assert len(parsed.rows) == 55  # 58 lines, 3 of them the header
    first = parsed.rows[0]
    assert first.kind == "METAR" and first.text.startswith("METAR WIDN 01") and first.text.endswith("=")
    assert first.runway == "04" and first.notes == ()
    speci = [r for r in parsed.rows if r.kind == "SPECI"]
    assert len(speci) == 5
    manual = next(r for r in speci if r.logged_at == _t("2026-11-01T06:16:29"))
    assert manual.notes == ("manually created condition",)
    assert "RETS" in manual.text and "(" not in manual.text
    assert all(r.type == "metar" for r in parsed.rows)


def test_a_met_report_log_has_routine_reports_and_specials() -> None:
    parsed = reports.parse_text(fixture_text("cdp1_METREPORT.20261101.log"), "metreport")
    assert parsed.warnings == 0
    assert len(parsed.rows) == 57
    assert {r.kind for r in parsed.rows} == {"MET REPORT", "SPECIAL"}
    assert sum(r.kind == "SPECIAL" for r in parsed.rows) == 10
    assert all(r.text.endswith("=") for r in parsed.rows)


def test_a_taf_is_its_heading_and_the_lines_up_to_its_end() -> None:
    parsed = reports.parse_text(fixture_text("cdp1_TAF.20261101.log"), "taf")
    assert parsed.warnings == 0
    assert [(r.logged_at.strftime("%H:%M:%S"), r.bulletin) for r in parsed.rows] == [
        ("05:11:15", "FTID32 WIDN 010500"),
        ("17:01:09", "FTID32 WIDN 011700"),
        ("23:00:54", "FTID32 WIDN 012300"),
    ]
    assert parsed.rows[0].text == (
        "TAF WIDN 010500Z 0106/0206 18007KT 9999 SCT017\nPROB30 TEMPO 0106/0110 4000 TSRA FEW015CB="
    )
    assert all(r.kind == "TAF" and r.runway is None for r in parsed.rows)


# ------------------------------------------------------------------------------------------ edge cases
HEADER = "METAR/SPECI Report\r\nReport Started on: 07/11/2026 for WIDN\r\nYYYY/MM/DD HH:MM:SS METAR/SPECI\r\n"


def test_a_line_still_being_written_is_left_for_the_next_read() -> None:
    text = (
        HEADER
        + "2026/11/07 00:29:33 METAR WIDN 070030Z VRB01KT 9999 FEW017 28/25 Q1012 NOSIG= (04)\r\n"
        + "2026/11/07 00:59:42 METAR WIDN 070100Z VRB03KT 99"
    )
    parsed = reports.parse_text(text, "metar")
    assert [r.text[:24] for r in parsed.rows] == ["METAR WIDN 070030Z VRB01"]
    assert parsed.warnings == 0


def test_lines_that_cannot_be_read_are_counted() -> None:
    text = (
        HEADER
        + "garbage without a time\r\n"
        + "2026/13/07 00:29:33 METAR WIDN 070030Z VRB01KT 9999 FEW017 28/25 Q1012 NOSIG= (04)\r\n"
        + "2025/11/07 00:29:33 METAR WIDN 070030Z VRB01KT 9999 FEW017 28/25 Q1012 NOSIG= (04)\r\n"
        + "2026/11/07 01:30:00 METAR WIDN 070130Z VRB01KT 9999 FEW017 28/25 Q1012 NOSIG= (04)\r\n"
        + "2026/11/07 00:59:42 METAR WIDN 070100Z VRB03KT 9999 FEW017 29/25 Q1012 NOSIG= (04)\r\n"
    )
    parsed = reports.parse_text(
        text, "metar", not_before=_t("2025-12-24T00:00:00"), not_after=_t("2026-11-07T01:02:00")
    )
    assert [r.logged_at for r in parsed.rows] == [_t("2026-11-07T00:59:42")]
    assert parsed.warnings == 4  # no time, a bad date, before coverage, in the future (E5)


def test_tafs_amended_unfinished_and_cut_short() -> None:
    text = (
        "TAF Report\nReport Started on: 07/01/2026 for WIDN\nYYYY/MM/DD HH:MM:SS TAF\n"
        "2026/01/07 05:08:11 FTID32 WIDN 070500     \n"
        "TAF AMD WIDN 070500Z 0706/0806 01010KT 8000 SCT017\n"
        "TEMPO 0706/0710 RA=\n"
        "2026/01/07 11:08:11 FTID32 WIDN 071100\n"
        "TAF WIDN 071100Z 0712/0812 VRB02KT 9999 SCT017\n"  # never reaches "=": kept, counted
        "2026/01/07 17:01:00 FTID32 WIDN 071700\n"
        "TAF WIDN 071700Z 0718/0818 VRB02KT 9999 SCT017\n"  # still being written at the end of the file
    )
    parsed = reports.parse_text(text, "taf")
    assert [(r.kind, r.bulletin) for r in parsed.rows] == [
        ("TAF AMD", "FTID32 WIDN 070500"),
        ("TAF", "FTID32 WIDN 071100"),
    ]
    assert parsed.rows[0].text == "TAF AMD WIDN 070500Z 0706/0806 01010KT 8000 SCT017\nTEMPO 0706/0710 RA="
    assert parsed.warnings == 1


def test_notes_and_kinds() -> None:
    long = "ceiling or vertical visibility lowering through 1500, amount of cloud coverage below 1500 feet"
    assert reports.split_notes(f"SPECI WIDN 011900Z AUTO 4900 BR= ({long}) (04)") == (
        "SPECI WIDN 011900Z AUTO 4900 BR=",
        (long,),
        "04",
    )
    assert reports.split_notes("MET REPORT WIDN 070030Z TREND NOSIG= ") == (
        "MET REPORT WIDN 070030Z TREND NOSIG=",
        (),
        None,
    )
    assert reports.split_notes("METAR WIDN 070030Z 9999") == ("METAR WIDN 070030Z 9999", (), None)
    assert [
        reports.kind_of(x)
        for x in ("MET REPORT WIDN", "SPECIAL WIDN", "SPECI WIDN", "TAF COR WIDN", "SYNOP x")
    ] == [
        "MET REPORT",
        "SPECIAL",
        "SPECI",
        "TAF COR",
        "SYNOP",
    ]


# ------------------------------------------------------------------------------------------ merging
def _line(t: str, cdp: int) -> tuple:  # type: ignore[type-arg]
    return (_t(t), cdp, "METAR", (), "04", None)


def test_both_cdps_copies_are_one_report() -> None:
    merged = reports.merge_copies(
        [_line("2026-11-01T05:12:04", CDP2), _line("2026-11-01T05:11:15", CDP1)], PREF
    )
    assert [(m.logged_at, m.cdp_ids) for m in merged] == [(_t("2026-11-01T05:11:15"), [CDP1, CDP2])]


def test_a_report_sent_twice_or_far_apart_stays_two() -> None:
    lines = [
        _line("2026-11-07T23:28:05", CDP1),
        _line("2026-11-07T23:29:02", CDP1),  # CDP1 sent it again
        _line("2026-11-07T23:29:10", CDP2),
        _line("2026-11-07T23:33:00", CDP2),  # four minutes later: another sending
    ]
    merged = reports.merge_copies(lines, PREF)
    # CDP2's copy goes with the nearer of CDP1's two sendings
    assert [(m.logged_at.strftime("%H:%M:%S"), m.cdp_ids) for m in merged] == [
        ("23:28:05", [CDP1]),
        ("23:29:02", [CDP1, CDP2]),
        ("23:33:00", [CDP2]),
    ]
    assert reports.MATCH_WINDOW == timedelta(minutes=2)  # the widest pair seen between the CDPs is 117 s
