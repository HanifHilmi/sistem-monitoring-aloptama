"""A signed-in page load does not exhaust the API's connection pool (NFR-PERF-001).

A site page asks for each sensor's series, flags and detections at once. On staging (2026-11-05) the flag and
detection requests of a signed-in user each held a connection while waiting for a second one for the session, so
the pool (4 + 1, as here) stalled for its 30-second timeout and answered 500. The session is now looked up first.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.browser import Browser, _add_user

pytestmark = pytest.mark.integration

SYS = "/api/v1/systems/WIDN-CAT3"
PERIOD = {"from": "2026-11-03T00:00:00Z", "to": "2026-11-04T00:00:00Z"}


async def test_a_burst_of_signed_in_requests_is_answered(engine: AsyncEngine) -> None:
    await _add_user(engine, "burst-viewer", "viewer")
    async with Browser() as viewer:
        assert (await viewer.login("burst-viewer")).status_code == 200
        requests = [(f"{SYS}/assets", {}), (f"{SYS}/problems", {})]
        for component in ("ATRH", "BARO", "ANEM", "CEL", "RVR", "PWX"):
            scope = {**PERIOD, "scope": f"component:04:{component}"}
            requests += [
                (f"{SYS}/flags", scope),
                (f"{SYS}/detections", scope),
                (
                    f"{SYS}/minutes",
                    {
                        "day": "2026-11-03",
                        "scope": scope["scope"],
                    },
                ),
            ]
        start = time.monotonic()
        answers = await asyncio.gather(*(viewer.get(path, params=q) for path, q in requests * 2))
        elapsed = time.monotonic() - start
    assert [r.status_code for r in answers] == [200] * len(answers), [
        r.text[:120] for r in answers if r.status_code != 200
    ]
    assert elapsed < 20, f"{len(answers)} requests took {elapsed:.1f} s"
