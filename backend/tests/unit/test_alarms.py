"""AWOS alarm files (R3.1, FR-ING-008): reading a file, merging the two CDPs' rows, and the starting mapping (D4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from simola import alarms
from simola.registry import Cdp, Component, Site, System
from tests.conftest import fixture_text

LAYOUT = {
    "04": ("RWY04", "04", ("DCP", "ATRH", "BARO", "ANEM", "RVR", "CEL", "PWX")),
    "M": ("RWYMID", "middle", ("DCP", "ATRH", "BARO", "ANEM", "RAIN", "SOLR", "LIGH")),
    "22": ("RWY22", "22", ("DCP", "ATRH", "BARO", "ANEM", "RVR", "CEL", "PWX")),
}
CDP1, CDP2 = 1, 2
PREF = {CDP1: 1, CDP2: 2}


def _system() -> System:
    sites = []
    cid = 0
    for sid, (station, (code, slug, comps)) in enumerate(LAYOUT.items(), start=1):
        components = []
        for c in comps:
            cid += 1
            components.append(Component(cid, sid, c, c == "DCP", c, c, cid, (), (), None, None))
        sites.append(Site(sid, code, station, slug, code, code, sid, tuple(components)))
    return System(
        1,
        "WIDN-CAT3",
        "AWOS_CAT3",
        "sla_ola",
        "x",
        "x",
        "WIDN",
        datetime(2025, 12, 24, tzinfo=UTC),
        (Cdp(CDP1, "CDP1", 1), Cdp(CDP2, "CDP2", 2)),
        tuple(sites),
    )


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


# ------------------------------------------------------------------------------------------ parsing
def test_reads_a_real_file_with_crlf_and_trailing_tabs() -> None:
    parsed = alarms.parse_text(fixture_text("cdp2_091ALARM.20261103.dat"))
    assert parsed.warnings == 0
    assert len(parsed.rows) == 7
    first = parsed.rows[0]
    assert first == alarms.AlarmRow(
        _t("2026-11-03T10:43:50"),
        "DCPA_Missing",
        "error",
        "pending",
        True,
        "DCP 04 Communication Error - check connections",
    )
    # "...Performance Error<TAB><CR>" loses the tab and the line end
    assert parsed.rows[4].message == "Present Weather Sensor 22 Possible Degraded Performance Error"


def test_message_keeps_its_commas_and_bad_rows_are_counted() -> None:
    text = "\r\n".join(
        [
            "DD/MM/YYYY HH:MM:SS,Site Identifier,Alarm Name,Type,State,Active,Message",
            "05/11/2026 10:40:33,WIDN,GPSCommError,Error,Pending,TRUE,Check cable, then port, then device\t",
            "05/11/2026 10:40:33,WIDN,GPSCommError,error,pending,true,Check cable, then port, then device",
            "31/02/2026 10:00:00,WIDN,GPSCommError,error,pending,true,no such day",
            "05/11/2026 10:41:00,WIDN,GPSCommError,info,pending,true,unknown type",
            "05/11/2026 10:42:00,WIDN,GPSCommError,error,pending,maybe,unknown active",
            "05/11/2026 10:43:00,WIDN,GPSCommError,error,pending",
            "",
        ]
    )
    parsed = alarms.parse_text(text)
    # the second row is the first one written differently: stored once
    assert [r.message for r in parsed.rows] == ["Check cable, then port, then device"]
    assert parsed.rows[0].type == "error" and parsed.rows[0].state == "pending" and parsed.rows[0].active
    assert parsed.warnings == 4


def test_rows_before_coverage_or_in_the_future_are_skipped() -> None:
    text = "\n".join(
        [
            "01/01/1970 00:00:00,WIDN,BPOutOfRangeWarning,warning,pending,true,Range of readings",  # clock reset
            "06/11/2026 12:00:00,WIDN,BPOutOfRangeWarning,warning,pending,false,Range of readings",
            "06/11/2026 12:05:00,WIDN,BPOutOfRangeWarning,warning,pending,true,Range of readings",  # future
        ]
    )
    parsed = alarms.parse_text(
        text, not_before=_t("2025-12-24T00:00:00"), not_after=_t("2026-11-06T12:02:00")
    )
    assert [r.time for r in parsed.rows] == [_t("2026-11-06T12:00:00")]
    assert parsed.warnings == 2


# ------------------------------------------------------------------------------------------ merging
def _row(t: str, cdp: int, active: bool = True, state: str = "pending", msg: str = "DCP 04 lost") -> tuple:  # type: ignore[type-arg]
    return (_t(t), cdp, "error", state, active, msg)


def test_both_cdps_logging_the_same_change_is_one_change() -> None:
    rows = [
        _row("2026-11-02T01:28:07", CDP2),  # CDP2 logged it 85 s after CDP1
        _row("2026-11-02T01:26:42", CDP1),
        _row("2026-11-03T10:43:50", CDP2),
        _row("2026-11-03T10:43:49", CDP1),
    ]
    events = alarms.merge_rows(rows, PREF)
    assert [(e.time, e.cdp_ids) for e in events] == [
        (_t("2026-11-02T01:26:42"), [CDP1, CDP2]),
        (_t("2026-11-03T10:43:49"), [CDP1, CDP2]),
    ]
    assert all(e.raised for e in events)  # raised again with no clear logged in between


def test_rows_further_apart_or_from_the_same_cdp_stay_apart() -> None:
    rows = [
        _row("2026-11-03T10:00:00", CDP1),
        _row("2026-11-03T10:03:00", CDP2),  # 3 minutes later: another change
        _row("2026-11-03T10:03:30", CDP2),  # the same CDP again: another change
        _row("2026-11-03T10:03:40", CDP1, msg="other text"),  # different content
    ]
    events = alarms.merge_rows(rows, PREF)
    assert [e.cdp_ids for e in events] == [[CDP1], [CDP2], [CDP2], [CDP1]]


def test_acknowledging_does_not_raise_and_a_clear_ends_it() -> None:
    rows = [
        _row("2026-11-03T10:00:00", CDP1),
        _row("2026-11-03T10:20:00", CDP1, state="acknowledged"),
        _row("2026-11-03T11:00:00", CDP1, active=False, state="acknowledged"),
        _row("2026-11-03T12:00:00", CDP1, state="acknowledged"),  # an "acknowledged" raise after a clear
    ]
    events = alarms.merge_rows(rows, PREF)
    assert [(e.active, e.raised) for e in events] == [
        (True, True),
        (True, False),
        (False, False),
        (True, True),
    ]


def test_merging_is_the_same_whichever_order_the_cdps_were_read() -> None:
    rows = [
        _row("2026-11-03T10:43:50", CDP2),
        _row("2026-11-03T10:43:49", CDP1),
        _row("2026-11-03T10:45:00", CDP1, active=False),
    ]
    a = alarms.merge_rows(rows, PREF)
    b = alarms.merge_rows(list(reversed(rows)), PREF)
    assert [(e.time, e.cdp_ids, e.active) for e in a] == [(e.time, e.cdp_ids, e.active) for e in b]


# ------------------------------------------------------------------------------------------ mapping (D4, E12)
def _place(name: str) -> dict[str, object]:
    system = _system()
    p = alarms.seed_place(system, name)
    return alarms.place_view(system, p.kind, p.site_id, p.component_type)


def test_every_known_name_starts_on_a_place() -> None:
    assert len(alarms.KNOWN_NAMES) == 75
    unplaced = [n for n in alarms.KNOWN_NAMES if _place(n)["kind"] == "unmapped"]
    assert unplaced == []


def test_the_letter_after_dcp_is_the_site_and_the_rest_the_sensor() -> None:
    assert _place("DCPA_Missing") == {"kind": "component", "site": "04", "component": "DCP"}
    assert _place("DCPB_Missing") == {"kind": "component", "site": "middle", "component": "DCP"}
    assert _place("DCPC_VISC_DirtyWindowWarning") == {"kind": "component", "site": "22", "component": "RVR"}
    assert _place("DCPA_CHIA_DoorOpenWarning") == {"kind": "component", "site": "04", "component": "CEL"}
    assert _place("DCP6498CpsbDegradedError") == {"kind": "component", "site": "22", "component": "PWX"}
    assert _place("DCPB_LightningCommError") == {"kind": "component", "site": "middle", "component": "LIGH"}
    assert _place("DCPB_windSensorWarning") == {"kind": "component", "site": "middle", "component": "ANEM"}
    assert _place("BPAIsManualWarning") == {"kind": "component", "site": "04", "component": "BARO"}


def test_station_wide_and_site_alarms() -> None:
    for name in (
        "GPSActiveError",
        "GPSHWError",
        "AFTNSocketFailedPortConnectionWarning",
        "BPOutOfRangeWarning",
    ):
        assert _place(name)["kind"] == "station", name
    assert _place("RLS0_Missing") == {"kind": "site", "site": "04", "component": None}


def test_a_new_name_arrives_not_assigned() -> None:
    assert _place("DCPA_NewSensorError") == {"kind": "unmapped", "site": None, "component": None}
    assert _place("GPSSomethingNew") == {"kind": "unmapped", "site": None, "component": None}


def test_admin_choices_are_checked_against_the_system() -> None:
    system = _system()
    assert alarms.resolve_place(system, "component", "middle", "LIGH").component_type == "LIGH"
    assert alarms.resolve_place(system, "site", "22", "ignored").component_type is None
    assert alarms.resolve_place(system, "station", "04", "RVR") == alarms.Place("station")
    for kind, site, comp, code in (
        ("component", "04", "LIGH", "component_not_found"),  # no lightning sensor at Runway 04
        ("site", "99", None, "site_not_found"),
        ("component", None, "RVR", "site_not_found"),
    ):
        try:
            alarms.resolve_place(system, kind, site, comp)
        except alarms.PlaceError as exc:
            assert exc.code == code
        else:
            raise AssertionError(f"{kind} {site} {comp} accepted")


def test_scopes_and_place_codes() -> None:
    comp = {"kind": "component", "site": "04", "component": "RVR"}
    site = {"kind": "site", "site": "04", "component": None}
    station = {"kind": "station", "site": None, "component": None}
    assert alarms.place_code(comp) == "component:04:RVR"
    assert alarms.place_code(site) == "site:04"
    assert alarms.place_code(station) == "station"
    assert alarms.in_scope(comp, "site:04") and alarms.in_scope(site, "site:04")
    assert alarms.in_scope(comp, "component:04:RVR") and not alarms.in_scope(site, "component:04:RVR")
    assert not alarms.in_scope(station, "site:04") and alarms.in_scope(station, "station")
    assert alarms.in_scope(station, None)


def test_match_window_covers_the_gaps_seen_between_cdps() -> None:
    # 578 of 622 CDP2 rows have a CDP1 row within 2 minutes; the largest pair seen is 85 s apart.
    assert alarms.MATCH_WINDOW == timedelta(minutes=2)
