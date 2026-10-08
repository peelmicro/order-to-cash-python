"""The order-scoped despatch: a pure function across the stock items an order holds (R36; F6, F7).

`despatch_order` calls `StockItem.consume` on each item in the order given (the SA-4 lock order),
which moves that item's `reserved` reservations of the order to `consumed` and lowers BOTH of its
counters (FS11). One line is built per consumed reservation, 1:1, never merged (F7: the despatched
units are the reserved units), and, when anything was consumed, exactly one `DespatchAdvice` is
created with its one fact. Nothing consumed is `NothingToDespatch`: no advice, no fact.

The CALLER decides the real R36 refusal (no `reserved` reservation) and the F8 repeat BEFORE
calling this, from the reservations under the lock and the `despatches` table: this function sees
only items, and an order whose reservations are all `consumed` looks to it exactly like one whose
reservations are all `released`.

Every identifier minted here comes from the required `new_id` (FS24, #8 id 49), in this order:
the advice id, then one line id per consumed reservation in consumption order, then the fact's
event id. Three kinds of mint site, each guarded separately.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from otc_fulfillment.domain.despatch_advice import DespatchAdvice, DespatchLine
from otc_fulfillment.domain.order_stock_reservation import StockContext
from otc_fulfillment.domain.reservation import Reservation
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import DespatchReference, Quantity, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class DespatchOrderInput:
    order_reference: str
    correlation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class Despatched:
    advice: DespatchAdvice


@dataclass(frozen=True, slots=True)
class NothingToDespatch:
    """No item held a `reserved` reservation of the order: no advice and no fact (R36)."""


type DespatchOutcome = Despatched | NothingToDespatch


def despatch_order(
    items: Sequence[StockItem],
    request: DespatchOrderInput,
    despatch_reference: DespatchReference,
    context: StockContext,
    new_id: Callable[[], UniqueId],
) -> DespatchOutcome:
    consumed: list[tuple[StockItem, Reservation]] = []
    for item in items:
        consumed.extend(
            (item, reservation) for reservation in item.consume(request.order_reference)
        )
    if not consumed:
        return NothingToDespatch()

    first_item, first_reservation = consumed[0]
    advice_id = new_id()
    lines = [
        DespatchLine(id=new_id(), product_code=item.product_code, units=Quantity(reservation.units))
        for item, reservation in consumed
    ]
    event_id = new_id()
    advice = DespatchAdvice.create(
        advice_id=advice_id,
        event_id=event_id,
        despatch_reference=despatch_reference,
        despatch_date=context.occurred_at,
        order_reference=request.order_reference,
        company_code=first_item.company_code,
        retailer_code=first_reservation.retailer_code,
        lines=lines,
        correlation_id=request.correlation_id,
        causation_id=context.causation_id,
    )
    return Despatched(advice=advice)
