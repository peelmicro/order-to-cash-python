"""`SagaCommandSweeper.run_once()`: the durability backstop (`design.md` 9.7; SO3, SO5, SO16).

Claims a due batch (rows `pending` past the grace window, and `parked` rows whose back-off elapsed,
each with a lease), then dispatches EVERY claimed row concurrently in a `TaskGroup` through
`dispatcher.dispatch_claimed(row)`:

* never `dispatch(order_id, kind)`, which would try to claim a row this sweeper already leases and
  silently do nothing (#8's production defect, L12);
* never through the fast path or the `otc_cqrs` dispatcher: the sweeper backs those up, so it must
  not depend on them;
* concurrently, so a sweep is bounded by one worst-case dispatch instead of `batch x worst case`,
  and every row finishes inside one lease. `SagaSettings` refuses a lease shorter than twice that
  worst case.

Each child catches `Exception` (a `TaskGroup` would otherwise cancel its siblings, L8);
`CancelledError` propagates. `run_once` returns when every child has finished, so a sweep never
overlaps its own rows.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from otc_orders.application.ports.saga_command_store import ClaimedCommand
from otc_orders.infrastructure.saga.command_dispatcher import DispatchOutcome

log = logging.getLogger("otc_orders.saga.sweeper")


class ClaimsDueCommands(Protocol):
    async def claim_due(self, batch_limit: int) -> list[ClaimedCommand]: ...


class DispatchesClaimedCommands(Protocol):
    async def dispatch_claimed(self, row: ClaimedCommand) -> DispatchOutcome: ...


@dataclass(frozen=True, slots=True)
class SweepResult:
    claimed: int
    sent: int
    parked: int
    failed: int
    rejected: int = 0


class SagaCommandSweeper:
    def __init__(
        self,
        *,
        ledger: ClaimsDueCommands,
        dispatcher: DispatchesClaimedCommands,
        batch_limit: int,
    ) -> None:
        self._ledger = ledger
        self._dispatcher = dispatcher
        self._batch_limit = batch_limit

    async def run_once(self) -> SweepResult:
        rows = await self._ledger.claim_due(self._batch_limit)
        outcomes: dict[int, DispatchOutcome | None] = {}
        async with asyncio.TaskGroup() as group:
            for index, row in enumerate(rows):
                group.create_task(self._dispatch(index, row, outcomes))
        return SweepResult(
            claimed=len(rows),
            sent=sum(1 for o in outcomes.values() if o is DispatchOutcome.SENT),
            parked=sum(1 for o in outcomes.values() if o is DispatchOutcome.PARKED),
            failed=sum(1 for o in outcomes.values() if o is None),
            rejected=sum(1 for o in outcomes.values() if o is DispatchOutcome.REJECTED),
        )

    async def _dispatch(
        self, index: int, row: ClaimedCommand, outcomes: dict[int, DispatchOutcome | None]
    ) -> None:
        try:
            outcomes[index] = await self._dispatcher.dispatch_claimed(row)
        except Exception:
            outcomes[index] = None
            log.exception(
                "sweeper dispatch failed; the row stays leased and is re-claimed after the lease",
                extra={
                    "correlationId": str(row.order_id),
                    "command": row.kind.value,
                    "attempts": row.attempts,
                },
            )
