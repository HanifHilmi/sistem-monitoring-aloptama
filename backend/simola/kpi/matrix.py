"""Availability matrix for the performance board: rows (SLA, CDPs, OLA, sites, components) x period buckets.

Every cell is computed from the same daily counts as the KPIs, so a row's total always equals the KPI figure
for the whole period (FR-KPI-001).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from simola.kpi.engine import Counts, availability, ola_ratio, ratio_pct, site_ratio
from simola.registry import System

Bucket = Literal["day", "week", "month"]


def bucket_start(d: date, bucket: Bucket) -> date:
    if bucket == "day":
        return d
    if bucket == "week":
        return d - timedelta(days=d.weekday())  # ISO week, Monday
    return d.replace(day=1)


def bucket_starts(first: date, last: date, bucket: Bucket) -> list[date]:
    """Bucket start dates covering [first, last], each clipped to the period start."""
    out: list[date] = []
    d = first
    while d <= last:
        b = max(bucket_start(d, bucket), first)
        if not out or out[-1] != b:
            out.append(b)
        d += timedelta(days=1)
    return out


def _group(days: dict[date, Counts], first: date, last: date, bucket: Bucket) -> list[tuple[date, Counts]]:
    starts = bucket_starts(first, last, bucket)
    grouped: dict[date, Counts] = {s: Counts() for s in starts}
    for d, c in days.items():
        if first <= d <= last:
            grouped[max(bucket_start(d, bucket), first)].merge(c)
    return [(s, grouped[s]) for s in starts]


def build_matrix(
    system: System, days: dict[date, Counts], first: date, last: date, bucket: Bucket
) -> dict[str, Any]:
    buckets = _group(days, first, last, bucket)
    total = Counts()
    for _, c in buckets:
        total.merge(c)

    def row(key: str, kind: str, scope: tuple[str, int], **meta: Any) -> dict[str, Any]:
        return {
            "key": key,
            "kind": kind,
            **meta,
            "cells": [availability(*c.get(scope)) for _, c in buckets],
            "total": availability(*total.get(scope)),
        }

    rows: list[dict[str, Any]] = [row("sla", "sla", ("sla", system.id))]
    rows += [row(f"cdp:{c.code}", "cdp", ("cdp_flow", c.id), cdp=c.code) for c in system.cdps]
    rows.append(
        {
            "key": "ola",
            "kind": "ola",
            "cells": [{"pct": ratio_pct(ola_ratio(system, c))} for _, c in buckets],
            "total": {"pct": ratio_pct(ola_ratio(system, total))},
        }
    )
    for site in system.sites:
        v, e = site_ratio(system, total, site.id)
        rows.append(
            {
                "key": f"site:{site.slug}",
                "kind": "site",
                "site": site.slug,
                "cells": [availability(*site_ratio(system, c, site.id)) for _, c in buckets],
                "total": availability(v, e),
            }
        )
        for comp in site.components:
            rows.append(
                row(
                    f"component:{site.slug}:{comp.type_code}",
                    "component",
                    ("component", comp.id),
                    site=site.slug,
                    type=comp.type_code,
                    is_dcp=comp.is_dcp,
                )
            )
    return {
        "bucket": bucket,
        "buckets": [
            {"start": s, "end": min(bucket_end(s, bucket), last + timedelta(days=1))} for s, _ in buckets
        ],
        "rows": rows,
    }


def bucket_end(start: date, bucket: Bucket) -> date:
    """Exclusive end date of the (unclipped) bucket that contains ``start``."""
    if bucket == "day":
        return start + timedelta(days=1)
    if bucket == "week":
        return bucket_start(start, "week") + timedelta(days=7)
    nxt = start.replace(day=28) + timedelta(days=4)
    return nxt.replace(day=1)
