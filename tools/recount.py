#!/usr/bin/env python3
"""Independent recount of SIMOLA figures from the CDP files (PRD SM-1, §15.6).

Deliberately shares NO code with the SIMOLA backend: its own parser, its own merge, its own counting.
Compares the result with the SIMOLA API for whole UTC months and exits non-zero on any difference.

    python3 tools/recount.py --cdp1 /mnt/<cdp1-share-mount> --cdp2 /mnt/<cdp2-share-mount> \
        --api http://127.0.0.1:18080 --month 2026-09 --month 2026-10
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Station -> {field: (start, end)}; text fields end with "!". "_ALL" = every non-gust field of the station.
SLICES = {
    "04": {"WS": (19, 24), "WD": (24, 29), "TEMP": (79, 84), "RH": (89, 93), "QNH": (124, 130),
           "RVR": (176, 182), "LR1": (218, 222), "PW!": (306, 312),
           "_ALL": [(19, 24), (24, 29), (79, 84), (84, 89), (89, 93), (124, 130), (142, 148),
                    (160, 166), (166, 168), (170, 176), (176, 182), (182, 184), (218, 222), (228, 258),
                    (288, 294), (306, 312)]},
    "M": {"WS": (39, 44), "WD": (44, 49), "TEMP": (94, 99), "RH": (104, 108), "QNH": (130, 136),
          "RA": (294, 300), "SOL": (326, 331), "LTX!": (332, 364),
          "_ALL": [(39, 44), (44, 49), (94, 99), (99, 104), (104, 108), (130, 136),
                   (148, 154), (294, 300), (326, 331), (332, 364)]},
    "22": {"WS": (59, 64), "WD": (64, 69), "TEMP": (109, 114), "RH": (119, 123), "QNH": (136, 142),
           "RVR": (200, 206), "LR1": (223, 227), "PW!": (316, 322),
           "_ALL": [(59, 64), (64, 69), (109, 114), (114, 119), (119, 123), (136, 142),
                    (154, 160), (194, 200), (200, 206), (206, 208), (223, 227), (258, 288), (300, 306),
                    (316, 322)]},
}
# Mandatory fields per component (decision B4a); DCP = any field of the site present.
COMPONENTS = {
    "04": {"ATRH": ["TEMP", "RH"], "BARO": ["QNH"], "ANEM": ["WS", "WD"], "RVR": ["RVR"], "CEL": ["LR1"], "PWX": ["PW!"]},
    "M": {"ATRH": ["TEMP", "RH"], "BARO": ["QNH"], "ANEM": ["WS", "WD"], "RAIN": ["RA"], "SOLR": ["SOL"], "LIGH": ["LTX!"]},
    "22": {"ATRH": ["TEMP", "RH"], "BARO": ["QNH"], "ANEM": ["WS", "WD"], "RVR": ["RVR"], "CEL": ["LR1"], "PWX": ["PW!"]},
}
SLUG = {"04": "04", "M": "middle", "22": "22"}


def present(token: str, text_field: bool) -> bool:
    t = token.strip()
    if t and (set(t) == {"/"} or t in ("M", "MM", "N/A", "---")):
        return False
    if text_field or not t:
        return True
    try:
        float(t.replace(",", "."))
        return True
    except ValueError:
        return False


def read_day(root: Path, day: datetime) -> dict[datetime, str]:
    f = root / "oneminute" / f"091OneMinute.{day:%Y%m%d}.dat"
    if not f.exists():
        return {}
    out: dict[datetime, str] = {}
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[4:]:
        if not line.strip():
            continue
        try:
            ts = datetime.strptime(f"{line[4:12]} {line[13:15]} {line[16:18]}", "%Y%m%d %H %M").replace(tzinfo=UTC)
        except ValueError:
            continue
        if ts.date() == day.date():
            out[ts] = line.ljust(400)
    return out


TEXT_SLICES = {(166, 168), (228, 258), (258, 288), (306, 312), (316, 322), (332, 364)}


def all_missing(line: str, station: str) -> bool:
    """True when every (non-gust) field of the station is missing; gusts follow wind by rule."""
    return all(not present(line[a:b], (a, b) in TEXT_SLICES) for a, b in SLICES[station]["_ALL"])


def recount(cdp1: Path, cdp2: Path, start: datetime, end: datetime) -> dict:
    c = {"flow": {"CDP1": 0, "CDP2": 0}, "sla": 0, "components": {}}
    day = start
    while day < end:
        l1, l2 = read_day(cdp1, day), read_day(cdp2, day)
        c["flow"]["CDP1"] += len(l1)
        c["flow"]["CDP2"] += len(l2)
        c["sla"] += len(set(l1) | set(l2))
        for t in set(l1) | set(l2):
            for st, comps in COMPONENTS.items():
                line = l1.get(t)
                if line is None or (all_missing(line, st) and t in l2 and not all_missing(l2[t], st)):
                    line = l2[t]
                any_field = not all_missing(line, st)
                c["components"].setdefault((SLUG[st], "DCP"), 0)
                c["components"][(SLUG[st], "DCP")] += int(any_field)
                for comp, fields in comps.items():
                    ok = all(present(line[SLICES[st][f][0]:SLICES[st][f][1]], f.endswith("!")) for f in fields)
                    c["components"][(SLUG[st], comp)] = c["components"].get((SLUG[st], comp), 0) + int(ok)
        day += timedelta(days=1)
    return c


def api_kpis(base: str, system: str, start: datetime, end: datetime) -> dict:
    q = urllib.parse.urlencode({"from": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
    with urllib.request.urlopen(f"{base}/api/v1/systems/{system}/kpis?{q}", timeout=120) as r:  # noqa: S310
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp1", type=Path, required=True)
    ap.add_argument("--cdp2", type=Path, required=True)
    ap.add_argument("--api", required=True)
    ap.add_argument("--system", default="WIDN-CAT3")
    ap.add_argument("--month", action="append", required=True, help="YYYY-MM (repeatable)")
    a = ap.parse_args()
    failures = 0
    for month in a.month:
        y, m = map(int, month.split("-"))
        start = datetime(y, m, 1, tzinfo=UTC)
        end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=UTC)
        mine = recount(a.cdp1, a.cdp2, start, end)
        theirs = api_kpis(a.api, a.system, start, end)
        pairs = [("SLA up", mine["sla"], theirs["sla"]["valid"])]
        for cdp in theirs["cdps"]:
            pairs.append((f"{cdp['code']} flow", mine["flow"][cdp["code"]], cdp["uptime"]["valid"]))
        for site in theirs["sites"]:
            for comp in site["components"]:
                pairs.append((f"{site['slug']} {comp['type']}", mine["components"].get((site["slug"], comp["type"])),
                              comp["availability"]["valid"]))
        bad = [(n, x, y_) for n, x, y_ in pairs if x != y_]
        failures += len(bad)
        print(f"{month}: {len(pairs) - len(bad)}/{len(pairs)} figures match "
              f"(SLA {theirs['sla']['valid']}/{theirs['sla']['expected']} = {theirs['sla']['pct']} %)")
        for n, x, y_ in bad:
            print(f"  MISMATCH {n}: recount={x} simola={y_}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
