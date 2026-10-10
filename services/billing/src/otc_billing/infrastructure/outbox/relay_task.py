"""Billing's COPY of Orders' `infrastructure/outbox/relay_task.py` (the canonical).

The canonical: `services/orders/src/otc_orders/infrastructure/outbox/relay_task.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_billing` and `ORDERS_FACTS_TOPIC` -> `BILLING_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""

import asyncio
import contextlib
import logging
from typing import Protocol

from otc_billing.infrastructure.outbox.relay import RelayResult

log = logging.getLogger("otc_billing.outbox.relay_task")


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
