"""Domain event -> wire fact: one function per event class, no arithmetic.

`Money` becomes its `int` minor units (`.amount`), the references and GLNs their `.value`, enums
their token, every instant goes through `wire_instant` (OI19: the stored millisecond, the envelope's
and the payload's are the same one). No `Decimal`, no `float`, no `/` on this path.

`narrow` is the single place an unknown event class is refused; `build_fact` then has one `match`
case per class (`assert_never` makes a fifth class a type error) and builds the typed
`Envelope[<payload model>]`. The envelope is parametrised by the CONCRETE payload class on purpose:
pydantic serialises a field by its declared type, so `Envelope[WireModel]` would write `{}`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import assert_never

from otc_contracts import Envelope, WireModel, wire_instant
from otc_contracts.generated import asyncapi
from otc_orders.domain.events import (
    OrderCancelled,
    OrderCompleted,
    OrderConfirmed,
    OrderEvent,
    OrderPlaced,
    OrderPlacedLine,
)
from otc_orders.domain.value_objects.compensation_step import CompensationStep
from otc_orders.infrastructure.outbox.errors import UnmappedDomainEventError


@dataclass(frozen=True, slots=True)
class BuiltFact:
    """A typed envelope and the payload it carries (the payload's text is what the row stores)."""

    envelope: WireModel
    payload: WireModel
    occurred_at: datetime  # the envelope's `occurredAt`, whole milliseconds: what the row stores


def narrow(event: object) -> OrderEvent:
    match event:
        case OrderPlaced() | OrderConfirmed() | OrderCompleted() | OrderCancelled():
            return event
        case _:
            raise UnmappedDomainEventError(type(event).__name__)


def _line_payload(line: OrderPlacedLine) -> asyncapi.OrderLine:
    return asyncapi.OrderLine(
        product_code=line.product_code,
        description=line.description,
        quantity=line.quantity.value,
        unit_price=line.unit_price.amount,
        line_discount=line.line_discount.amount,
    )


def _step_payload(step: CompensationStep) -> asyncapi.CompensationStep:
    return asyncapi.CompensationStep(
        step=asyncapi.Step(step.step.value),
        event_id=None if step.event_id is None else step.event_id.value,
        event_type=step.event_type,
        occurred_at=wire_instant(step.occurred_at),
        summary=step.summary,
    )


def placed_payload(event: OrderPlaced) -> asyncapi.OrderPlacedPayload:
    lines: Sequence[asyncapi.OrderLine] = [_line_payload(line) for line in event.lines]
    return asyncapi.OrderPlacedPayload(
        order_reference=event.order_reference.value,
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        buyer_gln=event.buyer_gln.value,
        supplier_gln=event.supplier_gln.value,
        currency=event.currency,
        order_date=wire_instant(event.order_date),
        lines=list(lines),
        initial_amount=event.initial_amount.amount,
        initial_discount=event.initial_discount.amount,
        total_amount=event.total_amount.amount,
        notes=event.notes,
    )


def confirmed_payload(event: OrderConfirmed) -> asyncapi.OrderConfirmedPayload:
    return asyncapi.OrderConfirmedPayload(
        order_reference=event.order_reference.value,
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        currency=event.currency,
        total_amount=event.total_amount.amount,
        confirmed_at=wire_instant(event.confirmed_at),
    )


def completed_payload(event: OrderCompleted) -> asyncapi.OrderCompletedPayload:
    return asyncapi.OrderCompletedPayload(
        order_reference=event.order_reference.value,
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        currency=event.currency,
        total_amount=event.total_amount.amount,
        completed_at=wire_instant(event.completed_at),
    )


def cancelled_payload(event: OrderCancelled) -> asyncapi.OrderCancelledPayload:
    return asyncapi.OrderCancelledPayload(
        order_reference=event.order_reference.value,
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        cancellation_reason=asyncapi.CancellationReason(event.cancellation_reason.value),
        cancelled_at=wire_instant(event.cancelled_at),
        compensation_steps=[_step_payload(step) for step in event.compensation_steps],
        note=event.note,
    )


def _envelope[P: WireModel](
    envelope_type: type[Envelope[P]], event: OrderEvent, payload: P, occurred_at: datetime
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


def build_fact(event: OrderEvent) -> BuiltFact:
    """The typed envelope of a (narrowed) domain event. The caller has run the R11 guard."""
    at = wire_instant(event.occurred_at)
    match event:
        case OrderPlaced():
            placed = placed_payload(event)
            envelope: WireModel = _envelope(
                Envelope[asyncapi.OrderPlacedPayload], event, placed, at
            )
            return BuiltFact(envelope=envelope, payload=placed, occurred_at=at)
        case OrderConfirmed():
            confirmed = confirmed_payload(event)
            envelope = _envelope(Envelope[asyncapi.OrderConfirmedPayload], event, confirmed, at)
            return BuiltFact(envelope=envelope, payload=confirmed, occurred_at=at)
        case OrderCompleted():
            completed = completed_payload(event)
            envelope = _envelope(Envelope[asyncapi.OrderCompletedPayload], event, completed, at)
            return BuiltFact(envelope=envelope, payload=completed, occurred_at=at)
        case OrderCancelled():
            cancelled = cancelled_payload(event)
            envelope = _envelope(Envelope[asyncapi.OrderCancelledPayload], event, cancelled, at)
            return BuiltFact(envelope=envelope, payload=cancelled, occurred_at=at)
        case _:
            assert_never(event)
