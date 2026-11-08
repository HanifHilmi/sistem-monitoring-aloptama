from __future__ import annotations

import gzip
import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """On GitHub Actions, errors in a test's setup or teardown become annotations too (failures inside a test
    already do), so they can be read without signing in to GitHub."""
    if os.environ.get("GITHUB_ACTIONS") and report.failed and report.when != "call":
        text = str(report.longrepr)[-3000:]
        msg = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"\n::error title={report.nodeid} ({report.when} error)::{msg}", flush=True)


os.environ.setdefault(
    "SIMOLA_DATABASE_URL",
    os.environ.get("SIMOLA_TEST_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:1/test"),
)


def fixture_text(name: str) -> str:
    return gzip.decompress((FIXTURES / f"{name}.gz").read_bytes()).decode("utf-8", errors="replace")


def missing_minutes(minutes: set[datetime], day: str) -> list[str]:
    start = datetime.combine(datetime.fromisoformat(day).date(), time(0), tzinfo=UTC)
    return [
        (start + timedelta(minutes=i)).strftime("%H:%M")
        for i in range(1440)
        if start + timedelta(minutes=i) not in minutes
    ]


@pytest.fixture
def cdp_share_root(tmp_path: Path) -> Path:
    """Lay out fixtures like the real shares: <root>/<cdp>/oneminute/091OneMinute.<date>.dat"""
    for gz in FIXTURES.glob("cdp*_091OneMinute.*.dat.gz"):
        cdp, name = gz.name[: -len(".gz")].split("_", 1)
        target = tmp_path / cdp / "oneminute"
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(gzip.decompress(gz.read_bytes()))
    return tmp_path
