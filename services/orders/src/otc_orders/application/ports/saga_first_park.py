"""The hook a command's FIRST park runs (`R29`, `OR3`; `design.md` 5.6).

The dispatcher calls it after `ledger.park(...)` returned, on every park; the hook decides whether
this is the first (a single claim statement) and does the rest. Kept as a port so the dispatcher
names no persistence and no broker.
"""

from typing import Protocol

from otc_orders.application.ports.saga_command_store import ClaimedCommand


class SagaFirstPark(Protocol):
    async def on_parked(self, row: ClaimedCommand, *, total_attempts: int, last_error: str) -> None:
        """Append `order.saga_failed.v1` and dead-letter the triggering envelope, once per row."""
        ...
