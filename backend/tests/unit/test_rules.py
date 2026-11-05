"""Validity rules (FR-DQ-001..003, R2.4): parameters, boundaries, which rule applies, and merging runs into the
stored detections so the same data and rules always give the same detections and decisions are kept.

The SQL side (detection jobs, decisions changing the figures, the review queue) is in
tests/integration/test_detections.py, in CI.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from simola.dq import rules as R
from simola.dq.history import proposals


def ms(*pairs: tuple[int, float | None]) -> tuple[list[int], list[float]]:
    """Minutes with values; None leaves the minute out (missing)."""
    kept = [(m, v) for m, v in pairs if v is not None]
    return [m for m, _ in kept], [float(v) for _, v in kept]  # type: ignore[arg-type]


def spans(hits: list[R.Hit]) -> list[tuple[int, int]]:
    return [(h.start, h.end) for h in hits]


# ---------------------------------------------------------------------------- parameters
@pytest.mark.parametrize(
    ("rule_type", "params", "code"),
    [
        ("flat", {}, "invalid_rule_type"),
        ("range", {}, "range_needs_a_limit"),
        ("range", {"min": 5, "max": 5}, "invalid_range"),
        ("range", {"min": "5"}, "invalid_params"),
        ("stuck", {"minutes": 4}, "invalid_minutes"),
        ("stuck", {"minutes": 60.0}, "invalid_minutes"),
        ("stuck", {"minutes": 60, "ignore": "0"}, "invalid_ignore"),
        ("spike", {"max_change": 0}, "invalid_change"),
        ("spike", {"max_change": 2, "window": 61}, "invalid_window"),
    ],
)
def test_parameters_that_are_refused(rule_type: str, params: dict[str, Any], code: str) -> None:
    with pytest.raises(R.RuleError) as exc:
        R.normalize(rule_type, params)
    assert exc.value.code == code


def test_parameters_keep_only_what_the_rule_uses() -> None:
    assert R.normalize("range", {"max": 40, "minutes": 9}) == {"min": None, "max": 40.0}
    assert R.normalize("stuck", {"minutes": 120, "ignore": [0, 0, 100]}) == {
        "minutes": 120,
        "ignore": [0.0, 100.0],
    }
    assert R.normalize("spike", {"max_change": 3, "window": 1}) == {"max_change": 3.0}
    assert R.normalize("spike", {"max_change": 3, "window": 5}) == {"max_change": 3.0, "window": 5}


# ---------------------------------------------------------------------------- boundaries (FR-DQ-001.2)
def test_range_fires_outside_its_limits_only() -> None:
    m, v = ms((0, 10), (1, 40), (2, 40.1), (3, 42), (4, None), (5, 50), (6, 9.9))
    hits = R.apply("range", {"min": 10, "max": 40}, m, v)
    assert spans(hits) == [
        (2, 4),
        (5, 7),
    ]  # a missing minute splits a stretch; too high then too low does not
    assert hits[0].evidence == {"value": 40.1, "low": 40.1, "high": 42.0}
    assert hits[1].evidence == {"value": 50.0, "low": 9.9, "high": 50.0}


def test_stuck_needs_the_whole_run_and_a_missing_minute_breaks_it() -> None:
    m, v = ms((0, 5), (1, 5), (2, 5), (3, 6))
    assert spans(R.apply("stuck", {"minutes": 3}, m, v)) == [(0, 3)]
    assert R.apply("stuck", {"minutes": 4}, m, v) == []
    m, v = ms((0, 5), (1, 5), (2, None), (3, 5), (4, 5))
    assert R.apply("stuck", {"minutes": 3}, m, v) == []
    m, v = ms((0, 0), (1, 0), (2, 0))
    assert R.apply("stuck", {"minutes": 3, "ignore": [0.0]}, m, v) == []


def test_spike_compares_valid_minutes_only_and_exactly_the_limit_does_not_fire() -> None:
    m, v = ms((0, 10), (1, 12), (2, 14.5), (3, None), (4, 30), (5, 30))
    hits = R.apply("spike", {"max_change": 2}, m, v)
    assert [(h.start, h.evidence["change"]) for h in hits] == [(2, 2.5)]
    m, v = ms((0, 10), (1, 11), (2, 12), (3, 13))
    assert [h.start for h in R.apply("spike", {"max_change": 2.5, "window": 3}, m, v)] == [3]


# ---------------------------------------------------------------------------- which rule applies
def rule(rid: int, rtype: str, site: int | None, enabled: bool = True, field: str = "TEMP") -> R.RuleRow:
    return R.RuleRow(rid, "ATRH", field, rtype, False, 1, site, {}, enabled)


def test_a_site_rule_replaces_the_all_sites_rule_there_even_when_off() -> None:
    rules = [
        rule(1, "range", None),
        rule(2, "range", 7, enabled=False),
        rule(3, "spike", None),
        rule(4, "range", 8),
    ]
    assert [r.id for r in R.effective(rules, "ATRH", 7, "TEMP")] == [3]
    assert [r.id for r in R.effective(rules, "ATRH", 8, "TEMP")] == [4, 3]
    assert [r.id for r in R.effective(rules, "ATRH", 9, "TEMP")] == [1, 3]
    assert R.effective(rules, "ATRH", 9, "RH") == []


# ---------------------------------------------------------------------------- merging into stored detections
def ex(i: int, a: int, b: int, status: str = "suspect", value: float = 1.0) -> R.Existing:
    return R.Existing(i, a, b, status, {"value": value})


def test_merge_extends_inserts_and_drops() -> None:
    plan = R.merge(
        "range",
        [ex(1, 10, 20), ex(2, 50, 55), ex(3, 200, 210)],
        [R.Hit(15, 30, {"value": 1.0}), R.Hit(80, 90, {"value": 2.0})],
        (0, 100),
    )
    assert plan.updates == {1: R.Hit(10, 30, {"value": 1.0})}
    assert plan.inserts == [R.Hit(80, 90, {"value": 2.0})]
    assert plan.deletes == {2}  # inside the window and no longer firing; 3 lies outside the window


def test_decisions_are_kept_and_absorb_suspects() -> None:
    plan = R.merge(
        "range",
        [ex(1, 10, 20, "rejected"), ex(2, 18, 40), ex(3, 60, 70, "confirmed")],
        [R.Hit(12, 35, {"value": 1.0})],
        (0, 100),
    )
    assert plan.inserts == []  # a rejected stretch is not raised again for this rule version
    assert plan.updates == {1: R.Hit(10, 40, {"value": 1.0})}
    assert plan.deletes == {2}  # the suspect it absorbed; the confirmed one is never deleted


def test_two_touching_stuck_runs_of_different_values_stay_apart() -> None:
    plan = R.merge("stuck", [ex(1, 0, 100, value=5)], [R.Hit(100, 200, {"value": 6.0})], (100, 300))
    assert plan.inserts == [R.Hit(100, 200, {"value": 6.0})] and not plan.updates


@st.composite
def series(draw: st.DrawFn) -> dict[str, Any]:
    n = draw(st.integers(10, 400))
    values = draw(
        st.lists(
            st.one_of(st.none(), st.sampled_from([1.0, 1.0, 1.0, 2.0, 7.5, 30.0])), min_size=n, max_size=n
        )
    )
    cut = draw(st.integers(1, n - 1))
    rule_type = draw(st.sampled_from(R.RULE_TYPES))
    params = {
        "range": {"min": 0.5, "max": 7.0},
        "stuck": {"minutes": draw(st.integers(5, 40))},
        "spike": {"max_change": 3.0, "window": draw(st.integers(1, 3))},
    }[rule_type]
    return {"values": values, "cut": cut, "type": rule_type, "params": params}


@settings(max_examples=300, deadline=None)
@given(series())
def test_two_chunks_give_what_one_pass_gives(s: dict[str, Any]) -> None:
    """FR-DQ-003.1: the history is checked month by month, yet the detections equal a single pass over it."""
    m = [i for i, v in enumerate(s["values"]) if v is not None]
    v = [x for x in s["values"] if x is not None]
    rtype, params, cut, n = s["type"], s["params"], s["cut"], len(s["values"])
    whole = spans(R.apply(rtype, params, m, v))

    lb = R.lookback(rtype, params)
    stored: dict[int, R.Existing] = {}
    next_id = 1
    for a, b in ((0, cut), (cut, n)):
        part = [(mm, vv) for mm, vv in zip(m, v, strict=True) if a - lb <= mm < b]
        hits = [h for h in R.apply(rtype, params, [p[0] for p in part], [p[1] for p in part]) if h.end > a]
        plan = R.merge(rtype, list(stored.values()), hits, (a, b))
        for i in plan.deletes:
            stored.pop(i)
        for i, h in plan.updates.items():
            stored[i] = R.Existing(i, h.start, h.end, "suspect", h.evidence)
        for h in plan.inserts:
            stored[next_id] = R.Existing(next_id, h.start, h.end, "suspect", h.evidence)
            next_id += 1
    assert sorted((e.start, e.end) for e in stored.values()) == whole


# ---------------------------------------------------------------------------- proposed starting values (OPEN-08)
def test_proposals_from_a_history() -> None:
    stats = {
        "p001": 22.3,
        "p01": 23.3,
        "p999": 33.6,
        "min": -31.2,
        "max": 36.3,
        "run_p999_minutes": 18,
        "step_p9999": 0.7,
    }
    p = proposals("TEMP", "°C", stats)
    assert p["range"] == {"min": 19.5, "max": 36.4}
    assert p["stuck"] == {"minutes": 60}
    assert p["spike"] == {"max_change": 1.4}
    rain = proposals(
        "RA", "mm", {"p001": 0, "p01": 0, "p999": 4.2, "min": 0, "max": 9, "run_p999_minutes": 600}
    )
    assert (
        rain["range"]["min"] == 0
        and rain["stuck"] == {"minutes": 1200, "ignore": [0]}
        and "spike" not in rain
    )
    rh = proposals(
        "RH", "%", {"p001": 40, "p01": 45, "p999": 100, "min": 30, "max": 100, "run_p999_minutes": 30}
    )
    assert rh["range"]["max"] == 100
