"""The order-scoped operations: pure functions across the stock items an order names (F3).

F3 is a rule across aggregates (one `StockItem` per product), and R32 / R33 demand ONE fact per
order, so it lives here and never in a handler (`design.md` 5.3).

* `reserve_order` EVALUATES every product before it mutates any item: a short line rejects the
  whole order and creates no reservation at all (R33). Otherwise one `reserve` call per line (a
  repeated product yields two reservations) and one `StockReserved`.
* `release_order` calls `release` on each item in the order given and emits one `StockReleased` when
  anything was released; nothing released is `AlreadyReleased`, no fact (F5, FS9).
* The carrier of a fact (FS13) is the item of the first request line that resolves to a known item
  (reserve / reject), or of the first released reservation (release).
* Every identifier minted here, the reservation ids and the three facts' event ids, comes from the
  required `new_id` parameter (FS24, #8 id 49): four call sites, each guarded separately.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from otc_fulfillment.domain.events import (
    RejectionReason,
    ReleaseReason,
    ReservationRef,
    Shortage,
    StockRejected,
    StockReleased,
    StockReserved,
)
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import Quantity, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReserveLine:
    product_code: str
    units: Quantity


@dataclass(frozen=True, slots=True, kw_only=True)
class ReserveOrderInput:
    order_reference: str
    company_code: str
    retailer_code: str
    lines: tuple[ReserveLine, ...]
    correlation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseOrderInput:
    order_reference: str
    reason: ReleaseReason
    correlation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class StockContext:
    """What the application supplies: the instant (clock port) and the causation (request id)."""

    occurred_at: datetime
    causation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class Reserved:
    reservations: tuple[ReservationRef, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Rejected:
    shortages: tuple[Shortage, ...]
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class NoCarrier:
    """No line resolved to a known item: there is no aggregate to carry a fact (FS13)."""


type ReserveOutcome = Reserved | Rejected | NoCarrier


@dataclass(frozen=True, slots=True, kw_only=True)
class Released:
    released: tuple[ReservationRef, ...]


@dataclass(frozen=True, slots=True)
class AlreadyReleased:
    """Nothing was `reserved` any more (or ever): success, no fact (F5)."""


type ReleaseOutcome = Released | AlreadyReleased


def reserve_order(
    items: Mapping[str, StockItem],
    request: ReserveOrderInput,
    context: StockContext,
    new_id: Callable[[], UniqueId],
) -> ReserveOutcome:
    # Units per product, in first-appearance order (a dict is insertion-ordered).
    requested: dict[str, int] = {}
    for line in request.lines:
        requested[line.product_code] = requested.get(line.product_code, 0) + line.units.value

    carrier = next(
        (items[ln.product_code] for ln in request.lines if ln.product_code in items), None
    )
    if carrier is None:
        return NoCarrier()

    shortages: list[Shortage] = []
    unknown = False
    for product_code, units in requested.items():
        item = items.get(product_code)
        if item is None:
            unknown = True
            shortages.append(Shortage(product_code=product_code, requested=units, available=0))
        elif units > item.available_units:
            shortages.append(
                Shortage(product_code=product_code, requested=units, available=item.available_units)
            )

    if shortages:
        reason = RejectionReason.UNKNOWN_PRODUCT if unknown else RejectionReason.INSUFFICIENT_STOCK
        carrier.record_order_fact(
            StockRejected(
                event_id=new_id(),
                aggregate_id=carrier.id,
                correlation_id=request.correlation_id,
                causation_id=context.causation_id,
                occurred_at=context.occurred_at,
                order_reference=request.order_reference,
                company_code=request.company_code,
                retailer_code=request.retailer_code,
                shortages=tuple(shortages),
                reason=reason,
            )
        )
        return Rejected(shortages=tuple(shortages), reason=reason)

    refs: list[ReservationRef] = []
    for line in request.lines:
        reservation = items[line.product_code].reserve(
            reservation_id=new_id(),
            order_reference=request.order_reference,
            retailer_code=request.retailer_code,
            units=line.units,
        )
        refs.append(
            ReservationRef(
                reservation_id=reservation.id,
                product_code=line.product_code,
                units=reservation.units,
            )
        )
    carrier.record_order_fact(
        StockReserved(
            event_id=new_id(),
            aggregate_id=carrier.id,
            correlation_id=request.correlation_id,
            causation_id=context.causation_id,
            occurred_at=context.occurred_at,
            order_reference=request.order_reference,
            company_code=request.company_code,
            retailer_code=request.retailer_code,
            reservations=tuple(refs),
        )
    )
    return Reserved(reservations=tuple(refs))


def release_order(
    items: Sequence[StockItem],
    request: ReleaseOrderInput,
    context: StockContext,
    new_id: Callable[[], UniqueId],
) -> ReleaseOutcome:
    refs: list[ReservationRef] = []
    carrier: StockItem | None = None
    retailer_code: str | None = None
    for item in items:
        for reservation in item.release(request.order_reference):
            if carrier is None:
                carrier = item
                retailer_code = reservation.retailer_code
            refs.append(
                ReservationRef(
                    reservation_id=reservation.id,
                    product_code=item.product_code,
                    units=reservation.units,
                )
            )
    if carrier is None or retailer_code is None:
        return AlreadyReleased()
    carrier.record_order_fact(
        StockReleased(
            event_id=new_id(),
            aggregate_id=carrier.id,
            correlation_id=request.correlation_id,
            causation_id=context.causation_id,
            occurred_at=context.occurred_at,
            order_reference=request.order_reference,
            company_code=carrier.company_code,
            retailer_code=retailer_code,
            released=tuple(refs),
            reason=request.reason,
        )
    )
    return Released(released=tuple(refs))
