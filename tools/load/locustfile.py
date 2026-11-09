"""Load test (PRD §15.5): 20 virtual users doing J1-style navigation against staging with full history.

    uvx --from 'locust>=2.30' locust -f tools/load/locustfile.py --headless -u 20 -r 2 -t 5m \
        --host http://<web-container-address>:8080 --csv <out-dir>/load

Each user opens the dashboard (as its panel and cards ask: summary, latest reports, the month by day, outages,
calibration), the board (this month), sometimes switches to the year, opens a site (3-hour charts) and
sometimes widens it to 31 days, and now and then reads the METAR archive, a report search, the data-quality
summary and the definitions (R3), with a 1-3 s pause between pages, like the browser does. Signed-in pages
(alarms, exports) are not in it: the test runs without an account. At the end the targets are checked and the
exit code is 1 if one is missed:
  NFR-PERF-001  KPI summary and status: p95 <= 1.0 s for periods up to 1 year
  NFR-PERF-002  sensor chart, 31-day window, one component: p95 <= 1.5 s and response <= 500 KB
Never commit the address you test against: the repository is public (NFR-SEC-010).
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from locust import HttpUser, between, events, task

PERF_001 = {
    "display",
    "systems",
    "system",
    "status",
    "problems",
    "kpis 1 month",
    "kpis 1 year",
    "matrix 1 month",
    "matrix 1 year",
}
PERF_002 = "series 31 days"
LIMITS = {"PERF_001_P95_S": 1.0, "PERF_002_P95_S": 1.5, "PERF_002_MAX_BYTES": 500 * 1024}

registry: dict[str, Any] = {}
largest: dict[str, int] = defaultdict(int)


@events.test_start.add_listener
def discover(environment: Any, **_: Any) -> None:
    """Real identifiers from the API, so the test follows whatever the registry holds."""
    base = environment.host.rstrip("/")
    code = requests.get(f"{base}/api/v1/systems", timeout=30).json()[0]["code"]
    system = requests.get(f"{base}/api/v1/systems/{code}", timeout=30).json()
    registry["code"] = code
    registry["sites"] = {
        s["slug"]: [c["type"] for c in s["components"] if not c["is_dcp"]] for s in system["sites"]
    }


@events.request.add_listener
def track_size(name: str, response_length: int, **_: Any) -> None:
    largest[name] = max(largest[name], response_length)


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def month_bounds(now: datetime) -> tuple[datetime, datetime, datetime]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev = (start - timedelta(days=1)).replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return prev, start, nxt


class DailyCheck(HttpUser):
    wait_time = between(1, 3)

    def api(self, name: str, path: str, **params: str) -> None:
        self.client.get(f"/api/v1/systems/{registry['code']}{path}", params=params or None, name=name)

    @task(5)
    def dashboard(self) -> None:
        """What the dashboard asks for on opening (its panel and the public cards)."""
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        _, start, nxt = month_bounds(now)
        self.client.get("/api/v1/settings/display", name="display")
        self.client.get("/api/v1/systems", name="systems")
        self.api("system", "")
        self.api("status", "/status")
        self.api("problems", "/problems")
        self.api("reports latest", "/reports/latest")
        self.api("matrix 1 month", "/matrix", **{"from": iso(start), "to": iso(nxt), "bucket": "day"})
        self.api("outages 1 month", "/outages", **{"from": iso(start), "to": iso(nxt), "scope": "sla", "limit": "1"})
        self.api("outages 7 days", "/outages",
                 **{"from": iso(now - timedelta(days=7)), "to": iso(now), "scope": "ola", "limit": "4"})
        self.api("assets", "/assets")

    @task(1)
    def reports_and_quality(self) -> None:
        """The R3 public pages: METAR archive, a search, the data-quality summary and the definitions."""
        now = datetime.now(UTC)
        _, start, nxt = month_bounds(now)
        day = (now - timedelta(days=random.randint(1, 60))).date().isoformat()
        self.api("reports latest", "/reports/latest")
        self.api("reports day", "/reports", day=day, type=random.choice(["metar", "metreport", "taf"]))
        week = (now - timedelta(days=7)).date().isoformat()
        self.api("reports search", "/reports/search",
                 **{"from": week, "to": now.date().isoformat(), "type": "metar", "q": "SPECI"})
        self.api("data quality", "/data-quality", **{"from": iso(start), "to": iso(nxt)})
        self.client.get("/api/v1/definitions", name="definitions")

    @task(5)
    def board_month(self) -> None:
        self.client.get("/api/v1/settings/display", name="display")
        self.api("system", "")
        self.api("status", "/status")
        self.api("problems", "/problems")
        prev, start, nxt = month_bounds(datetime.now(UTC))
        self.api("matrix 1 month", "/matrix", **{"from": iso(start), "to": iso(nxt), "bucket": "day"})
        self.api("kpis 1 month", "/kpis", **{"from": iso(start), "to": iso(nxt)})
        self.api("kpis 1 month", "/kpis", **{"from": iso(prev), "to": iso(start)})

    @task(2)
    def board_year(self) -> None:
        now = datetime.now(UTC)
        start = datetime(now.year, 1, 1, tzinfo=UTC)
        prev, nxt = datetime(now.year - 1, 1, 1, tzinfo=UTC), datetime(now.year + 1, 1, 1, tzinfo=UTC)
        self.api("matrix 1 year", "/matrix", **{"from": iso(start), "to": iso(nxt), "bucket": "month"})
        self.api("kpis 1 year", "/kpis", **{"from": iso(start), "to": iso(nxt)})
        self.api("kpis 1 year", "/kpis", **{"from": iso(prev), "to": iso(start)})

    @task(4)
    def site(self) -> None:
        slug, components = random.choice(list(registry["sites"].items()))
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        self.api("status", "/status")
        for c in components:
            self.api("series 3 hours", f"/sites/{slug}/components/{c}/series",
                     **{"from": iso(now - timedelta(hours=3)), "to": iso(now)})
        if random.random() < 0.5:
            for c in components:
                self.api(PERF_002, f"/sites/{slug}/components/{c}/series",
                         **{"from": iso(now - timedelta(days=31)), "to": iso(now)})


@events.quitting.add_listener
def check_targets(environment: Any, **_: Any) -> None:
    stats = environment.stats
    failed = False
    print("\nTargets (p95 in seconds):")
    for entry in sorted(stats.entries.values(), key=lambda e: e.name):
        p95 = entry.get_response_time_percentile(0.95) / 1000
        if entry.name in PERF_001:
            limit, rule = LIMITS["PERF_001_P95_S"], "NFR-PERF-001"
        elif entry.name == PERF_002:
            limit, rule = LIMITS["PERF_002_P95_S"], "NFR-PERF-002"
        else:
            limit, rule = None, "info"
        ok = limit is None or p95 <= limit
        failed |= not ok
        size = largest[entry.name] / 1024
        print(f"  {'PASS' if ok else 'FAIL'}  {rule:<12} {entry.name:<16} p95 {p95:5.2f}"
              f"{f' (limit {limit})' if limit else '':<13} n={entry.num_requests:<5} largest {size:6.1f} KB")
    big = largest[PERF_002]
    size_ok = big <= LIMITS["PERF_002_MAX_BYTES"]
    failed |= not size_ok
    print(f"  {'PASS' if size_ok else 'FAIL'}  NFR-PERF-002 largest 31-day series {big / 1024:.1f} KB (limit 500 KB)")
    errors = stats.total.num_failures
    failed |= errors > 0
    print(f"  {'PASS' if errors == 0 else 'FAIL'}  errors       {errors} failed requests of {stats.total.num_requests}")
    if failed:
        environment.process_exit_code = 1
