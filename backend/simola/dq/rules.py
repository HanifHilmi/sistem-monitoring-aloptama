"""Validity rules (FR-DQ-001..003): range, stuck and spike over one field's minute values. Pure functions.

Minutes are whole minutes since the Unix epoch, ascending, and only minutes with a value are given: a missing value
never fires a rule, and a missing minute ends a stuck run and is never compared by a spike rule (FR-DQ-001.1).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

RULE_TYPES = ("range", "stuck", "spike")
STATUSES = ("suspect", "confirmed", "rejected")


class RuleError(ValueError):
    """A rule the API refuses; ``code`` is the stable error code the screens translate."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _number(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise RuleError("invalid_params")
    return float(v)


def normalize(rule_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """The parameters a rule of this type keeps, checked; RuleError otherwise."""
    if rule_type not in RULE_TYPES:
        raise RuleError("invalid_rule_type")
    if rule_type == "range":
        lo, hi = _number(params.get("min")), _number(params.get("max"))
        if lo is None and hi is None:
            raise RuleError("range_needs_a_limit")
        if lo is not None and hi is not None and lo >= hi:
            raise RuleError("invalid_range")
        return {"min": lo, "max": hi}
    if rule_type == "stuck":
        n = params.get("minutes")
        if not isinstance(n, int) or isinstance(n, bool) or not 5 <= n <= 1440:
            raise RuleError("invalid_minutes")
        ignore = params.get("ignore") or []
        if not isinstance(ignore, list) or len(ignore) > 10:
            raise RuleError("invalid_ignore")
        values = sorted({_number(v) for v in ignore} - {None})  # type: ignore[type-var]
        return {"minutes": n, **({"ignore": values} if values else {})}
    change = _number(params.get("max_change"))
    if change is None or change <= 0:
        raise RuleError("invalid_change")
    window = params.get("window", 1)
    if not isinstance(window, int) or isinstance(window, bool) or not 1 <= window <= 60:
        raise RuleError("invalid_window")
    return {"max_change": change, **({"window": window} if window > 1 else {})}


def lookback(rule_type: str, params: dict[str, Any]) -> int:
    """Minutes before a range that a rule needs to see a stretch whole: a run's start, a spike's earlier minute."""
    if rule_type == "stuck":
        return int(params["minutes"])
    if rule_type == "spike":
        return int(params.get("window", 1))
    return 0


@dataclass(frozen=True)
class Hit:
    start: int  # minute number
    end: int  # exclusive
    evidence: dict[str, float] = field(default_factory=dict)


def _r(v: float) -> float:
    return round(v, 3)


def apply(
    rule_type: str, params: dict[str, Any], minutes: Sequence[int], values: Sequence[float]
) -> list[Hit]:
    """The stretches one rule fires on, in time order."""
    if rule_type == "range":
        return _range(params.get("min"), params.get("max"), minutes, values)
    if rule_type == "stuck":
        return _stuck(int(params["minutes"]), set(params.get("ignore", [])), minutes, values)
    return _spike(float(params["max_change"]), int(params.get("window", 1)), minutes, values)


def _range(lo: float | None, hi: float | None, minutes: Sequence[int], values: Sequence[float]) -> list[Hit]:
    out: list[Hit] = []
    for m, v in zip(minutes, values, strict=True):
        if not ((lo is not None and v < lo) or (hi is not None and v > hi)):
            continue
        last = out[-1] if out else None
        if last is not None and last.end == m:
            low = min(last.evidence.get("low", last.evidence["value"]), v)
            high = max(last.evidence.get("high", last.evidence["value"]), v)
            out[-1] = Hit(
                last.start, m + 1, {"value": last.evidence["value"], "low": _r(low), "high": _r(high)}
            )
        else:
            out.append(Hit(m, m + 1, {"value": _r(v)}))
    return out


def _stuck(n: int, ignore: set[float], minutes: Sequence[int], values: Sequence[float]) -> list[Hit]:
    out: list[Hit] = []
    i = 0
    while i < len(minutes):
        j = i + 1
        while j < len(minutes) and minutes[j] == minutes[j - 1] + 1 and values[j] == values[i]:
            j += 1
        if values[i] not in ignore and j - i >= n:
            out.append(Hit(minutes[i], minutes[j - 1] + 1, {"value": _r(values[i])}))
        i = j
    return out


def _spike(limit: float, window: int, minutes: Sequence[int], values: Sequence[float]) -> list[Hit]:
    at = dict(zip(minutes, values, strict=True))
    out: list[Hit] = []
    for m, v in zip(minutes, values, strict=True):
        before = at.get(m - window)
        if before is None:
            continue
        change = v - before
        if abs(change) <= limit:
            continue
        last = out[-1] if out else None
        if last is not None and last.end == m:
            biggest = change if abs(change) > abs(last.evidence["change"]) else last.evidence["change"]
            out[-1] = Hit(last.start, m + 1, {"change": _r(biggest)})
        else:
            out.append(Hit(m, m + 1, {"change": _r(change)}))
    return out


# ---------------------------------------------------------------------------- which rule applies
@dataclass(frozen=True)
class RuleRow:
    """A rule with its latest version."""

    id: int
    component_type: str
    field: str
    type: str
    proposed: bool
    version: int
    site_id: int | None
    params: dict[str, Any]
    enabled: bool
    created_by: str = ""
    created_at: Any = None


def effective(rules: Sequence[RuleRow], component_type: str, site_id: int, field_code: str) -> list[RuleRow]:
    """The enabled rules that check this field at this site. A rule for the site replaces the all-sites rule of
    the same type there, even when the site's rule is off."""
    chosen: dict[str, RuleRow] = {}
    for r in rules:
        if r.component_type != component_type or r.field != field_code:
            continue
        if r.site_id is not None and r.site_id != site_id:
            continue
        current = chosen.get(r.type)
        if current is None or (current.site_id is None and r.site_id is not None):
            chosen[r.type] = r
    return [r for r in chosen.values() if r.enabled]


# ---------------------------------------------------------------------------- merging a run into what is stored
@dataclass(frozen=True)
class Existing:
    id: int
    start: int
    end: int
    status: str
    evidence: dict[str, float]


@dataclass
class Plan:
    inserts: list[Hit] = field(default_factory=list)
    updates: dict[int, Hit] = field(default_factory=dict)  # id -> new span and evidence
    deletes: set[int] = field(default_factory=set)


def _merge_evidence(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    if "change" in a or "change" in b:
        ca, cb = a.get("change", 0.0), b.get("change", 0.0)
        return {"change": ca if abs(ca) >= abs(cb) else cb}
    values = [x for e in (a, b) for x in (e.get("low"), e.get("high"), e.get("value")) if x is not None]
    out = {"value": a.get("value", b.get("value", 0.0))}
    if len(set(values)) > 1:
        out |= {"low": min(values), "high": max(values)}
    return out


_RANK = {"confirmed": 0, "rejected": 1, "suspect": 2}


def _joins(rule_type: str, a: Hit, b: Hit) -> bool:
    """Whether two stretches are one: overlapping, or touching (a stretch cut at a month boundary) unless they
    are two stuck runs of different values that happen to meet."""
    if a.start < b.end and b.start < a.end:
        return True
    if a.start != b.end and b.start != a.end:
        return False
    return rule_type != "stuck" or a.evidence.get("value") == b.evidence.get("value")


def merge(rule_type: str, existing: Sequence[Existing], hits: Sequence[Hit], window: tuple[int, int]) -> Plan:
    """How one run of one rule version on one component changes the stored detections.

    - A hit touching stored detections extends one of them (a decided one first, so a decision covers the whole
      stretch and a rejected stretch is never raised again for this rule version); suspects it absorbs go.
    - A hit touching nothing is a new suspect.
    - A suspect inside the evaluated window that no hit touches no longer holds (the data changed) and goes.
    Decided detections are never deleted.
    """
    a, b = window
    plan = Plan()
    spans = {e.id: Hit(e.start, e.end, e.evidence) for e in existing}
    status = {e.id: e.status for e in existing}
    touched: set[int] = set()
    for h in sorted(hits, key=lambda x: x.start):
        near = [i for i, s in spans.items() if i not in plan.deletes and _joins(rule_type, s, h)]
        if not near:
            plan.inserts.append(h)
            continue
        near.sort(key=lambda i: (_RANK[status[i]], spans[i].start, i))
        target = near[0]
        cur = spans[target]
        new = Hit(min(cur.start, h.start), max(cur.end, h.end), _merge_evidence(cur.evidence, h.evidence))
        for other in near[1:]:
            if status[other] == "suspect":
                o = spans[other]
                new = Hit(
                    min(new.start, o.start), max(new.end, o.end), _merge_evidence(new.evidence, o.evidence)
                )
                plan.deletes.add(other)
                plan.updates.pop(other, None)
                touched.add(other)
        if new != cur:
            plan.updates[target] = new
        spans[target] = new
        touched.add(target)
    for e in existing:
        if e.status == "suspect" and e.id not in touched and e.start >= a and e.end <= b:
            plan.deletes.add(e.id)
    return plan
