"""Domain event -> wire fact: one function per event class, no arithmetic.

References and identifiers become their `.value`, enums their token, every instant goes through
`wire_instant` (OI19: the stored millisecond, the envelope's and the payload's are the same one).
Unit counts are plain `int`s already; no `Decimal`, no `float`, no `/` on this path.

`narrow` is the single place an unknown event class is refused; `build_fact` then has one `match`
case per class (`assert_never` makes a fifth class a type error, as `OrderDespatched` was one until
feature 18 mapped it) and builds the typed `Envelope[<payload model>]`. The envelope is
parametrised by the CONCRETE payload class on purpose: pydantic serialises a field by its declared
type, so `Envelope[WireModel]` would write `{}`.

Service-specific, NOT a parity-guarded copy of Orders' module of the same name.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import assert_never

from otc_contracts import Envelope, WireModel, wire_instant
from otc_contracts.generated import asyncapi
from otc_fulfillment.domain.events import (
    DespatchedLine,
    FulfillmentEvent,
    OrderDespatched,
    ReservationRef,
    Shortage,
    StockRejected,
    StockReleased,
    StockReserved,
)
from otc_fulfillment.infrastructure.outbox.errors import UnmappedDomainEventError


@dataclass(frozen=True, slots=True)
class BuiltFact:
    """A typed envelope and the payload it carries (the payload's text is what the row stores)."""

    envelope: WireModel
    payload: WireModel
    occurred_at: datetime  # the envelope's `occurredAt`, whole milliseconds: what the row stores


def narrow(event: object) -> FulfillmentEvent:
    match event:
        case StockReserved() | StockRejected() | StockReleased() | OrderDespatched():
            return event
        case _:
            raise UnmappedDomainEventError(type(event).__name__)


def _reference(ref: ReservationRef) -> asyncapi.ReservationRef:
    return asyncapi.ReservationRef(
        reservation_id=ref.reservation_id.value, product_code=ref.product_code, units=ref.units
    )


def _shortage(shortage: Shortage) -> asyncapi.Shortage:
    return asyncapi.Shortage(
        product_code=shortage.product_code,
        requested=shortage.requested,
        available=shortage.available,
    )


def reserved_payload(event: StockReserved) -> asyncapi.StockReservedPayload:
    return asyncapi.StockReservedPayload(
        order_reference=event.order_reference,
        company_code=event.company_code,
        retailer_code=event.retailer_code,
        reservations=[_reference(ref) for ref in event.reservations],
    )


def rejected_payload(event: StockRejected) -> asyncapi.StockRejectedPayload:
    return asyncapi.StockRejectedPayload(
        order_reference=event.order_reference,
        company_code=event.company_code,
        retailer_code=event.retailer_code,
        shortages=[_shortage(shortage) for shortage in event.shortages],
        reason=asyncapi.Reason(event.reason.value),
    )


def released_payload(event: StockReleased) -> asyncapi.StockReleasedPayload:
    return asyncapi.StockReleasedPayload(
        order_reference=event.order_reference,
        company_code=event.company_code,
        retailer_code=event.retailer_code,
        released=[_reference(ref) for ref in event.released],
        reason=asyncapi.Reason1(event.reason.value),
    )


def despatched_payload(event: OrderDespatched) -> asyncapi.OrderDespatchedPayload:
    return asyncapi.OrderDespatchedPayload(
        order_reference=event.order_reference,
        despatch_reference=event.despatch_reference.value,
        despatch_date=wire_instant(event.despatch_date),
        company_code=event.company_code,
        retailer_code=event.retailer_code,
        lines=[_despatch_line(line) for line in event.lines],
    )


def _despatch_line(line: DespatchedLine) -> asyncapi.DespatchLine:
    return asyncapi.DespatchLine(product_code=line.product_code, units=line.units)


def _envelope[P: WireModel](
    envelope_type: type[Envelope[P]], event: FulfillmentEvent, payload: P, occurred_at: datetime
) -> Envelope[P]:
    """The ONE site that maps an event's identity and instant into an envelope."""
    return envelope_type(
        event_id=event.event_id.value,
        event_type=type(event).EVENT_TYPE,
        aggregate_id=event.aggregate_id.value,
        correlation_id=event.correlation_id.value,
        causation_id=event.causation_id.value,
        occurred_at=occurred_at,
        payload=payload,
    )


def build_fact(event: FulfillmentEvent) -> BuiltFact:
    """The typed envelope of a (narrowed) domain event. The caller has run the R11 guard."""
    at = wire_instant(event.occurred_at)
    match event:
        case StockReserved():
            reserved = reserved_payload(event)
            envelope: WireModel = _envelope(
                Envelope[asyncapi.StockReservedPayload], event, reserved, at
            )
            return BuiltFact(envelope=envelope, payload=reserved, occurred_at=at)
        case StockRejected():
            rejected = rejected_payload(event)
            envelope = _envelope(Envelope[asyncapi.StockRejectedPayload], event, rejected, at)
            return BuiltFact(envelope=envelope, payload=rejected, occurred_at=at)
        case StockReleased():
            released = released_payload(event)
            envelope = _envelope(Envelope[asyncapi.StockReleasedPayload], event, released, at)
            return BuiltFact(envelope=envelope, payload=released, occurred_at=at)
        case OrderDespatched():
            despatched = despatched_payload(event)
            envelope = _envelope(Envelope[asyncapi.OrderDespatchedPayload], event, despatched, at)
            return BuiltFact(envelope=envelope, payload=despatched, occurred_at=at)
        case _:
            assert_never(event)
