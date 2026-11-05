"""UTC and minute helpers. Periods are half-open [start, end) at minute resolution (PRD §7.3.1)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta

MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime: all SIMOLA times must be timezone-aware UTC")
    return dt.astimezone(UTC)


def floor_minute(dt: datetime) -> datetime:
    return ensure_utc(dt).replace(second=0, microsecond=0)


def ceil_minute(dt: datetime) -> datetime:
    f = floor_minute(dt)
    return f if f == ensure_utc(dt) else f + MINUTE


def day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def minutes_between(start: datetime, end: datetime) -> int:
    """Number of whole minutes m with start <= m < end (both minute-aligned)."""
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)


def iter_days(start: date, end_inclusive: date) -> Iterator[date]:
    d = start
    while d <= end_inclusive:
        yield d
        d += timedelta(days=1)


def intersect(
    a: tuple[datetime, datetime], b: tuple[datetime | None, datetime | None]
) -> tuple[datetime, datetime]:
    """Intersect [a0, a1) with [b0, b1), where None means unbounded. Empty results have end <= start."""
    lo = a[0] if b[0] is None else max(a[0], b[0])
    hi = a[1] if b[1] is None else min(a[1], b[1])
    return lo, hi


Span = tuple[datetime, datetime]  # half-open [start, end)


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    """Sorted, disjoint union of spans; touching spans are joined."""
    out: list[Span] = []
    for s, e in sorted(spans):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out
