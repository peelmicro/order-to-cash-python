"""`OutboxRelayTask.run(stop)`: the self-scheduled loop (OI6, L18-L20).

One `while` loop: `await relay.run_once()`, then an interruptible sleep (`wait_for(stop.wait(),
timeout=interval)`): never a fixed-interval timer and never a second task, so a cycle can never
overlap the next. `stop.set()` ends the loop AFTER the in-flight cycle completes (bounded by OI14);
a normal stop never cancels a cycle mid-publish, because a cancellation after an acknowledgement and
before the stamp turns into a duplicate on restart.

A failed cycle is logged with its traceback and the loop continues (L19: `except Exception`, never
`BaseException`); `asyncio.CancelledError` propagates (L8). The owner (feature 15's lifespan)
creates the task, and awaits it on shutdown after `stop.set()`: never fire-and-forget.
"""

import asyncio
import contextlib
import logging
from typing import Protocol

from otc_orders.infrastructure.outbox.relay import RelayResult

log = logging.getLogger("otc_orders.outbox.relay_task")


class RunsOutboxOnce(Protocol):
    async def run_once(self) -> RelayResult: ...


class OutboxRelayTask:
    def __init__(self, relay: RunsOutboxOnce, *, poll_interval: float, enabled: bool) -> None:
        self._relay = relay
        self._poll_interval = poll_interval
        self._enabled = enabled

    async def run(self, stop: asyncio.Event) -> None:
        if not self._enabled:
            return
        while not stop.is_set():
            try:
                await self._relay.run_once()
            except Exception:
                log.exception("outbox relay cycle failed; next cycle after the poll interval")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
