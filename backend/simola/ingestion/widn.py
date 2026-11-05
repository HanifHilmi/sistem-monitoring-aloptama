"""Parser for the AWOS WIDN daily 1-minute file ``oneminute/091OneMinute.<YYYYMMDD>.dat`` (FR-ING-002).

Format (verified against production files, 2025-12 .. 2026-11):
- 4 header lines, then one fixed-width record per minute for all three stations.
- Timestamp columns: date [4:12], hour [13:15], minute [16:18], in UTC.
- Field positions below started from v2's slices (``parsers.py::_SLICES``). v2 cut present weather to 6
  characters and the lightning text to 32; both are wider in the files (checked 2026-11-05) and are read in full.

Token rules:
- A run of ``/`` (one per character of the field)  -> missing (sensor offline).            [verified]
- ``M``, ``MM``, ``N/A``, ``---``                    -> missing (never observed; defensive). [PRD P]
- empty / whitespace                                 -> present and healthy: numeric 0, text "".
- unparseable numeric                                -> missing, counted as a parse warning.
- Gust rule: if WS or WD is missing, WGS/WGD are missing; otherwise a missing gust becomes 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

HEADER_LINES = 4
LINE_PAD = 400

_SLASH_RUN = re.compile(r"/+")
_MISSING_TOKENS = frozenset({"M", "MM", "N/A", "---"})

Value = float | str | None


@dataclass(frozen=True)
class FieldSlice:
    code: str
    start: int
    end: int
    scale: float | None  # None -> text field

    @property
    def is_text(self) -> bool:
        return self.scale is None


def _num(code: str, start: int, end: int, scale: float = 1.0) -> FieldSlice:
    return FieldSlice(code, start, end, scale)


def _txt(code: str, start: int, end: int) -> FieldSlice:
    return FieldSlice(code, start, end, None)


# Station code (as used in the file header) -> field slices.
STATION_SLICES: dict[str, tuple[FieldSlice, ...]] = {
    "04": (
        _num("WS", 19, 24),
        _num("WD", 24, 29),
        _num("WGS", 29, 34),
        _num("WGD", 34, 39),
        _num("TEMP", 79, 84, 0.1),
        _num("DEWP", 84, 89, 0.1),
        _num("RH", 89, 93),
        _num("QNH", 124, 130, 0.1),
        _num("DA", 142, 148),
        _num("ALS", 160, 166),
        _txt("D/N", 166, 168),
        _num("VIS", 170, 176),
        _num("RVR", 176, 182),
        _num("RLS", 182, 184),
        _num("LR1", 218, 222),
        _txt("SKY", 228, 258),
        _num("RA", 288, 294),
        _txt("PW", 306, 316),  # 10 wide: "VCTS DZ" (6 cut it to "VCTS D")
    ),
    "M": (
        _num("WS", 39, 44),
        _num("WD", 44, 49),
        _num("WGS", 49, 54),
        _num("WGD", 54, 59),
        _num("TEMP", 94, 99, 0.1),
        _num("DEWP", 99, 104, 0.1),
        _num("RH", 104, 108),
        _num("QNH", 130, 136, 0.1),
        _num("DA", 148, 154),
        _num("RA", 294, 300),
        _num("SOL", 326, 331),
        _txt("LTX", 332, LINE_PAD),  # free text to the end of the line (32 cut it)
    ),
    "22": (
        _num("WS", 59, 64),
        _num("WD", 64, 69),
        _num("WGS", 69, 74),
        _num("WGD", 74, 79),
        _num("TEMP", 109, 114, 0.1),
        _num("DEWP", 114, 119, 0.1),
        _num("RH", 119, 123),
        _num("QNH", 136, 142, 0.1),
        _num("DA", 154, 160),
        _num("VIS", 194, 200),
        _num("RVR", 200, 206),
        _num("RLS", 206, 208),
        _num("LR1", 223, 227),
        _txt("SKY", 258, 288),
        _num("RA", 300, 306),
        _txt("PW", 316, 326),  # 10 wide, up to SOL at 326
    ),
}


@dataclass
class StationRecord:
    values: dict[str, Value]
    all_missing: bool


@dataclass
class MinuteRecord:
    time: datetime
    stations: dict[str, StationRecord]


@dataclass
class ParseResult:
    records: list[MinuteRecord] = field(default_factory=list)
    warnings: int = 0
    skipped_lines: int = 0
    duplicate_minutes: int = 0


def is_missing_token(token: str) -> bool:
    return bool(token) and (_SLASH_RUN.fullmatch(token) is not None or token in _MISSING_TOKENS)


def parse_value(raw: str, fs: FieldSlice) -> tuple[Value, bool]:
    """Return (value, warning). ``raw`` is the unstripped slice."""
    token = raw.strip()
    if fs.is_text:
        if is_missing_token(token):
            return None, False
        return token, False
    if not token:
        return 0.0, False
    if is_missing_token(token):
        return None, False
    try:
        value = float(token.replace(",", "."))
    except ValueError:
        return None, True
    if fs.scale is not None and fs.scale != 1.0:
        value = round(value * fs.scale, 6)
    return value, False


def _apply_gust_rule(values: dict[str, Value]) -> None:
    if "WS" not in values:
        return
    wind_ok = values.get("WS") is not None and values.get("WD") is not None
    for gust in ("WGS", "WGD"):
        if gust not in values:
            continue
        if not wind_ok:
            values[gust] = None
        elif values[gust] is None:
            values[gust] = 0.0


def parse_timestamp(padded: str) -> datetime | None:
    date_s, hour_s, min_s = padded[4:12].strip(), padded[13:15].strip(), padded[16:18].strip()
    if not (date_s and hour_s and min_s):
        return None
    try:
        return datetime.strptime(f"{date_s} {hour_s} {min_s}", "%Y%m%d %H %M").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_text(content: str, stations: dict[str, tuple[FieldSlice, ...]] = STATION_SLICES) -> ParseResult:
    """Parse a whole file. If a minute appears twice, the later line wins (it is the newer write)."""
    result = ParseResult()
    by_time: dict[datetime, MinuteRecord] = {}
    for line in content.splitlines()[HEADER_LINES:]:
        if not line.strip():
            continue
        padded = line.ljust(LINE_PAD)
        ts = parse_timestamp(padded)
        if ts is None:
            result.skipped_lines += 1
            continue
        record = MinuteRecord(time=ts, stations={})
        for station, slices in stations.items():
            values: dict[str, Value] = {}
            for fs in slices:
                value, warn = parse_value(padded[fs.start : fs.end], fs)
                values[fs.code] = value
                result.warnings += int(warn)
            _apply_gust_rule(values)
            record.stations[station] = StationRecord(values, all(v is None for v in values.values()))
        if ts in by_time:
            result.duplicate_minutes += 1
        by_time[ts] = record
    result.records = sorted(by_time.values(), key=lambda r: r.time)
    return result


def file_name_for(day: datetime | str) -> str:
    stamp = day if isinstance(day, str) else day.strftime("%Y%m%d")
    return f"091OneMinute.{stamp}.dat"
