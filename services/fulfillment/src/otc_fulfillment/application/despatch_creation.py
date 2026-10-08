"""The `despatch.create` transactional unit (R36; F6, F7, F8; SA-4's despatch half).

```text
1. F8 fast path, no transaction: the order already has an advice -> reply it, created=False
2. SA-4 step 0, no transaction: StockReads.stock_keys_of_order; none -> NoReservedStockForDespatch
3. run(work):
   a. StockRepository.lock_order_items   -- the SAME lock stock.release takes (stock rows, then the
                                            order's reservations FOR UPDATE)
   b. a `reserved` reservation exists? no:
        any `consumed` -> F8 in-lock re-read of the advice (a concurrent despatch committed while we
                          waited) -> reply it, created=False; none found -> ConcurrentDespatchChange
        else (all released) -> NoReservedStockForDespatch
   c. allocate DES-######, despatch_order (pure), save the stock rows, save the advice + its fact
```

Two transactions on one order serialise on the first stock row, and whichever commits second
decides on the first's COMMITTED reservations: a release that wins leaves nothing to consume (3b,
`NoReservedStockForDespatch`); a despatch that wins makes the release answer `PRECONDITION_FAILED`.

Each `work` is RE-RUNNABLE (a deadlock victim is re-run whole, FS23): it receives the transaction
and its own arguments (bound with `functools.partial`), reads everything in THIS attempt and mints
its ids per attempt. The reply is built from the result only after `run()` returns, i.e. after the
commit.
"""

from collections.abc import Callable
from datetime import datetime
from functools import partial

from otc_fulfillment.application.messages import CreateDespatchCommand, DespatchResult
from otc_fulfillment.application.ports.stock_store import (
    ConcurrentDespatchChangeError,
    StockTransaction,
    distinct_stock_keys,
)
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.domain.order_despatch import (
    Despatched,
    DespatchOrderInput,
    NothingToDespatch,
    despatch_order,
)
from otc_fulfillment.domain.order_stock_reservation import StockContext
from otc_fulfillment.domain.reservation import ReservationStatus
from otc_shared_kernel import UniqueId


class NoReservedStockForDespatchError(Exception):
    """The order holds no reservation in status `reserved` and has no advice: it never held stock,
    or every reservation was released (R36). Answered `PRECONDITION_FAILED`: the order and its
    reservations exist, they are not in the state `despatch.create` requires."""

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            f"despatch.create: order {order_reference} holds no reservation in status "
            '"reserved": nothing to despatch'
        )
        self.order_reference = order_reference


async def _despatch_work(
    tx: StockTransaction,
    *,
    command: CreateDespatchCommand,
    keys: tuple[tuple[str, str], ...],
    now: datetime,
    new_id: Callable[[], UniqueId],
) -> DespatchResult:
    repository = tx.repository
    locked = await repository.lock_order_items(command.order_reference, keys)  # the SA-4 lock
    statuses = {r.status for r in locked.reservations_of_order}
    if ReservationStatus.RESERVED not in statuses:
        if ReservationStatus.CONSUMED in statuses:
            # F8, the in-lock re-read: a concurrent despatch committed while this one waited for the
            # lock. The read is a NEW statement under the pinned READ COMMITTED, so it sees that
            # commit (#8 id 54; at REPEATABLE READ it would be stale and the lock itself would have
            # raised 40001).
            existing = await tx.despatches.find_by_order_reference(command.order_reference)
            if existing is None:
                raise ConcurrentDespatchChangeError(command.order_reference)
            return DespatchResult(created=False, despatch=existing)
        raise NoReservedStockForDespatchError(command.order_reference)  # all released
    reference = await tx.despatch_numbers.next_reference()
    outcome = despatch_order(
        list(locked.items.values()),
        DespatchOrderInput(
            order_reference=command.order_reference, correlation_id=command.correlation_id
        ),
        reference,
        StockContext(occurred_at=now, causation_id=command.request_id),
        new_id,
    )
    match outcome:
        case NothingToDespatch():
            # unreachable: a `reserved` reservation was just seen under the lock
            raise NoReservedStockForDespatchError(command.order_reference)
        case Despatched():
            await repository.save()  # the reservations' status and both counters; emits no fact
            await tx.despatches.save(outcome.advice)  # the advice, its lines, its ONE fact
            return DespatchResult(created=True, despatch=outcome.advice.to_snapshot())


async def create(command: CreateDespatchCommand, scope: FulfillmentScope) -> DespatchResult:
    existing = await scope.reads.despatch_of_order(command.order_reference)
    if existing is not None:
        return DespatchResult(created=False, despatch=existing)
    keys = await scope.reads.stock_keys_of_order(command.order_reference)
    if not keys:
        raise NoReservedStockForDespatchError(command.order_reference)
    work = partial(
        _despatch_work,
        command=command,
        keys=distinct_stock_keys(keys),
        now=scope.clock.now(),
        new_id=scope.ids.new,
    )
    return await scope.transactions.run(work)
