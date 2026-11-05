"""A dead CDP share must not stall the worker (ingestion/share.py)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from simola.ingestion.share import ShareIO, ShareStuck


def _share_threads(name: str) -> int:
    return sum(t.name.startswith(f"share-{name}") for t in threading.enumerate())


async def _until_released(share: ShareIO) -> None:
    for _ in range(200):
        if share.stuck == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the blocked call never returned")


async def test_a_blocked_share_times_out_then_fails_at_once_until_it_answers() -> None:
    share = ShareIO("CDP1", timeout_s=0.2)
    answer = threading.Event()

    started = time.monotonic()
    with pytest.raises(ShareStuck, match=r"did not answer within 0\.2 s"):
        await share.run(lambda: answer.wait(5))
    assert 0.15 < time.monotonic() - started < 1.0
    assert share.stuck == 1

    # While that call is still blocked, new calls fail at once and start no thread.
    for _ in range(20):
        started = time.monotonic()
        with pytest.raises(ShareStuck, match="earlier call is still waiting"):
            await share.run(lambda: 1)
        assert time.monotonic() - started < 0.05
    assert _share_threads("CDP1") == 1

    answer.set()  # the CDP is back
    await _until_released(share)
    assert await share.run(lambda: 42) == 42


async def test_a_blocked_share_leaves_the_other_cdp_and_the_worker_free() -> None:
    cdp1, cdp2 = ShareIO("CDP1x", timeout_s=0.1), ShareIO("CDP2x", timeout_s=0.1)
    answer = threading.Event()
    with pytest.raises(ShareStuck):
        await cdp1.run(lambda: answer.wait(5))
    try:
        for _ in range(30):  # many ingestion cycles while CDP1 stays dead
            with pytest.raises(ShareStuck):
                await cdp1.run(lambda: None)
            assert await cdp2.run(lambda: "cdp2 file") == "cdp2 file"
        # The default thread pool (parsing, heartbeat) is untouched.
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "alive"), 1) == "alive"
        assert _share_threads("CDP1x") == 1
    finally:
        answer.set()
    await _until_released(cdp1)


async def test_errors_from_the_share_pass_through_and_do_not_count_as_stuck() -> None:
    share = ShareIO("CDP1y", timeout_s=1)

    def missing() -> None:
        raise FileNotFoundError("no such file")

    with pytest.raises(FileNotFoundError):
        await share.run(missing)
    assert share.stuck == 0
    assert await share.run(lambda: "ok") == "ok"


def test_a_stuck_share_is_handled_like_any_unreadable_share() -> None:
    # The ingestion cycle marks a CDP unavailable on OSError, TimeoutError or SourceUnavailable.
    assert issubclass(ShareStuck, TimeoutError)
