"""The reserve and release transactional units (`design.md` 6.2, 6.3, 7.3): plain functions over
ports.

Each `work` is RE-RUNNABLE (a deadlock victim is re-run whole, FS23): it receives the transaction
and its own arguments (bound with `functools.partial`) and nothing else, builds its aggregates from
rows read in THIS attempt and mints its ids per attempt. A business rejection is a RESULT, never a
raise (saga.md 7, SO6); the reply is built from the result only after `run()` returns, i.e. after
the commit.
"""

from collections.abc import Callable
from datetime import datetime
from functools import partial

from otc_fulfillment.application.messages import (
    ReleaseOutcomeKind,
    ReleaseResult,
    ReleaseStockCommand,
    ReserveOutcomeKind,
    ReserveResult,
    ReserveStockCommand,
)
from otc_fulfillment.application.ports.stock_store import StockTransaction, distinct_stock_keys
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.domain.events import ReservationRef
from otc_fulfillment.domain.order_stock_reservation import (
    AlreadyReleased,
    NoCarrier,
    Rejected,
    Released,
    ReleaseOrderInput,
    Reserved,
    ReserveLine,
    ReserveOrderInput,
    StockContext,
    release_order,
    reserve_order,
)
from otc_fulfillment.domain.snapshot import ReservationSnapshot
from otc_shared_kernel import UniqueId


class NoKnownStockItemError(Exception):
    """No line of a `stock.reserve` resolved to a known stock item: there is no aggregate to carry
    a fact (FS13). Answered `NOT_FOUND`; the transaction is rolled back."""

    def __init__(self, order_reference: str) -> None:
        super().__init__(f"no product named by order {order_reference} has a stock item")
        self.order_reference = order_reference


def _reference_of(reservation: ReservationSnapshot) -> ReservationRef:
    return ReservationRef(
        reservation_id=reservation.id,
        product_code=reservation.product_code,
        units=reservation.units,
    )


async def _reserve_work(
    tx: StockTransaction,
    *,
    command: ReserveStockCommand,
    now: datetime,
    new_id: Callable[[], UniqueId],
) -> ReserveResult:
    repository = tx.repository
    locked = await repository.lock_for_reserve(
        command.company_code,
        [line.product_code for line in command.lines],
        command.order_reference,
    )
    if locked.reservations_of_order:
        # FS5: a reservation in ANY status answers `already_reserved`: no domain call, no save.
        return ReserveResult(
            outcome=ReserveOutcomeKind.ALREADY_RESERVED,
            order_reference=command.order_reference,
            reservations=tuple(_reference_of(r) for r in locked.reservations_of_order),
        )
    outcome = reserve_order(
        locked.items,
        ReserveOrderInput(
            order_reference=command.order_reference,
            company_code=command.company_code,
            retailer_code=command.retailer_code,
            lines=tuple(
                ReserveLine(product_code=line.product_code, units=line.units)
                for line in command.lines
            ),
            correlation_id=command.correlation_id,
        ),
        StockContext(occurred_at=now, causation_id=command.request_id),
        new_id,
    )
    match outcome:
        case NoCarrier():
            raise NoKnownStockItemError(command.order_reference)
        case Rejected():
            await repository.save()
            return ReserveResult(
                outcome=ReserveOutcomeKind.REJECTED,
                order_reference=command.order_reference,
                shortages=outcome.shortages,
            )
        case Reserved():
            await repository.save()
            return ReserveResult(
                outcome=ReserveOutcomeKind.ACCEPTED,
                order_reference=command.order_reference,
                reservations=outcome.reservations,
            )


async def reserve(command: ReserveStockCommand, scope: FulfillmentScope) -> ReserveResult:
    work = partial(_reserve_work, command=command, now=scope.clock.now(), new_id=scope.ids.new)
    return await scope.transactions.run(work)


async def _release_work(
    tx: StockTransaction,
    *,
    command: ReleaseStockCommand,
    keys: tuple[tuple[str, str], ...],
    now: datetime,
    new_id: Callable[[], UniqueId],
) -> ReleaseResult:
    repository = tx.repository
    locked = await repository.lock_order_items(command.order_reference, keys)
    outcome = release_order(
        list(locked.items.values()),
        ReleaseOrderInput(
            order_reference=command.order_reference,
            reason=command.reason,
            correlation_id=command.correlation_id,
        ),
        StockContext(occurred_at=now, causation_id=command.request_id),
        new_id,
    )
    match outcome:
        case AlreadyReleased():
            return ReleaseResult(
                outcome=ReleaseOutcomeKind.ALREADY_RELEASED,
                order_reference=command.order_reference,
                released=(),
            )
        case Released():
            await repository.save()
            return ReleaseResult(
                outcome=ReleaseOutcomeKind.RELEASED,
                order_reference=command.order_reference,
                released=outcome.released,
            )


async def release(command: ReleaseStockCommand, scope: FulfillmentScope) -> ReleaseResult:
    # Step 0 (SA-4): a NON-LOCKING pre-read, outside any transaction. An order that holds no
    # reservation at all answers `already_released` WITHOUT opening a transaction (FS9).
    keys = await scope.reads.stock_keys_of_order(command.order_reference)
    if not keys:
        return ReleaseResult(
            outcome=ReleaseOutcomeKind.ALREADY_RELEASED,
            order_reference=command.order_reference,
            released=(),
        )
    work = partial(
        _release_work,
        command=command,
        keys=distinct_stock_keys(keys),
        now=scope.clock.now(),
        new_id=scope.ids.new,
    )
    return await scope.transactions.run(work)
