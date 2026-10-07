"""`SagaCommandSweeperTask.run(stop)`: the relay task's loop for the sweeper (`design.md` 9.7; L30).

`await sweeper.run_once()`, then an interruptible wait (`wait_for(stop.wait(), timeout=interval)`):
never a fixed-interval timer and never a second task per cycle, so a cycle can never overlap the
next. `stop.set()` ends the loop AFTER the in-flight cycle completes. A failed cycle is logged with
its traceback and the loop continues (`except Exception`, never `BaseException`); `CancelledError`
propagates. `enabled=False` returns at once.
"""

import asyncio
import contextlib
import logging
from typing import Protocol

log = logging.getLogger("otc_orders.saga.sweeper_task")


class SweepsOnce(Protocol):
    async def run_once(self) -> object: ...


class SagaCommandSweeperTask:
    def __init__(self, sweeper: SweepsOnce, *, interval: float, enabled: bool) -> None:
        self._sweeper = sweeper
        self._interval = interval
        self._enabled = enabled

    async def run(self, stop: asyncio.Event) -> None:
        if not self._enabled:
            return
        while not stop.is_set():
            try:
                await self._sweeper.run_once()
            except Exception:
                log.exception("saga sweeper cycle failed; next cycle after the interval")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
