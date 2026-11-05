"""File calls on a CDP's SMB share, run so that a dead share cannot stall the worker.

When a CDP drops off the network, a call on its share can block for minutes while the kernel waits for the
server. Each CDP therefore gets its own two threads. A caller gives up after ``timeout_s``, and while a call it
gave up on is still blocked, new calls for that CDP fail at once instead of tying up more threads. The other CDP,
file parsing and the heartbeat run on other threads and carry on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class ShareStuck(TimeoutError):
    """The share did not answer in time, or an earlier call on it is still waiting."""


def _consume(fut: asyncio.Future[Any]) -> None:
    # The caller may have stopped waiting; read the outcome so asyncio does not log it as unhandled.
    if not fut.cancelled():
        fut.exception()


class ShareIO:
    def __init__(self, name: str, timeout_s: float, threads: int = 2) -> None:
        self.name = name
        self.timeout_s = timeout_s
        self._pool = ThreadPoolExecutor(max_workers=threads, thread_name_prefix=f"share-{name}")
        self._stuck = 0

    @property
    def stuck(self) -> int:
        """Calls that timed out and are still blocked."""
        return self._stuck

    async def run[T](self, fn: Callable[[], T]) -> T:
        if self._stuck:
            raise ShareStuck(f"{self.name}: share not answering (an earlier call is still waiting)")
        fut = asyncio.get_running_loop().run_in_executor(self._pool, fn)
        fut.add_done_callback(_consume)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), self.timeout_s)
        except TimeoutError:
            self._stuck += 1
            fut.add_done_callback(self._released)
            raise ShareStuck(f"{self.name}: share did not answer within {self.timeout_s:g} s") from None

    def _released(self, _fut: asyncio.Future[Any]) -> None:
        self._stuck -= 1
