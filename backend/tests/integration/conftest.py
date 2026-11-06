from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.core.config import get_settings
from simola.core.db import make_engine, set_engine
from simola.migrations.runner import migrate

TEST_URL = os.environ.get("SIMOLA_TEST_DATABASE_URL")
pytestmark = pytest.mark.integration

LEAK_PROBE_ADDRESS = "192.0.2.77"  # RFC 5737 documentation address; must never appear in public responses


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if TEST_URL:
        return
    skip = pytest.mark.skip(reason="SIMOLA_TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def share_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    import gzip

    from tests.conftest import FIXTURES

    root = tmp_path_factory.mktemp("shares")
    for pattern, folder in (("cdp*_091OneMinute.*.dat.gz", "oneminute"), ("cdp*_091ALARM.*.dat.gz", "alarm")):
        for gz in FIXTURES.glob(pattern):
            cdp, name = gz.name[: -len(".gz")].split("_", 1)
            target = root / cdp / folder
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(gzip.decompress(gz.read_bytes()))
    return root


@pytest_asyncio.fixture(scope="session")
async def engine(share_root: Path) -> AsyncIterator[AsyncEngine]:
    assert TEST_URL
    os.environ["SIMOLA_DATABASE_URL"] = TEST_URL
    os.environ["SIMOLA_CDP_PATHS"] = json.dumps(
        {"CDP1": str(share_root / "cdp1"), "CDP2": str(share_root / "cdp2")}
    )
    os.environ["SIMOLA_CDP_ADDRESSES"] = json.dumps({"CDP1": LEAK_PROBE_ADDRESS, "CDP2": LEAK_PROBE_ADDRESS})
    get_settings.cache_clear()
    eng = make_engine(TEST_URL)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await eng.dispose()
    await migrate(get_settings().asyncpg_dsn)
    eng = make_engine(TEST_URL)
    set_engine(eng)
    yield eng
    set_engine(None)
    await eng.dispose()
