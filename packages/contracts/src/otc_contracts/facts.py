"""The fact registry: `eventType` -> the generated envelope model that parses it.

Hand-written on purpose and checked against `specs/shared/asyncapi.yaml` at test time
(`test_every_event_schema_has_a_model_and_a_registry_entry`), so a fact added to the spec without a
registry entry fails a test instead of being silently dropped. Registration is explicit (no
import-time decorator), as everywhere else in this repository.
"""

import json
from typing import cast

from otc_contracts.generated.asyncapi import (
    CreditApprovedEvent,
    CreditRejectedEvent,
    CreditReleasedEvent,
    InvoiceIssuedEvent,
    OrderCancelledEvent,
    OrderCompletedEvent,
    OrderConfirmedEvent,
    OrderDespatchedEvent,
    OrderPlacedEvent,
    OrderSagaFailedEvent,
    PaymentReceivedEvent,
    StockRejectedEvent,
    StockReleasedEvent,
    StockReservedEvent,
)
from otc_contracts.wire import WireModel, from_wire_json

type FactEvent = (
    OrderPlacedEvent
    | StockReservedEvent
    | StockRejectedEvent
    | StockReleasedEvent
    | CreditApprovedEvent
    | CreditRejectedEvent
    | CreditReleasedEvent
    | OrderConfirmedEvent
    | OrderDespatchedEvent
    | InvoiceIssuedEvent
    | PaymentReceivedEvent
    | OrderCompletedEvent
    | OrderCancelledEvent
    | OrderSagaFailedEvent
)

FACT_MODELS: dict[str, type[WireModel]] = {
    "order.placed.v1": OrderPlacedEvent,
    "stock.reserved.v1": StockReservedEvent,
    "stock.rejected.v1": StockRejectedEvent,
    "stock.released.v1": StockReleasedEvent,
    "credit.approved.v1": CreditApprovedEvent,
    "credit.rejected.v1": CreditRejectedEvent,
    "credit.released.v1": CreditReleasedEvent,
    "order.confirmed.v1": OrderConfirmedEvent,
    "order.despatched.v1": OrderDespatchedEvent,
    "invoice.issued.v1": InvoiceIssuedEvent,
    "payment.received.v1": PaymentReceivedEvent,
    "order.completed.v1": OrderCompletedEvent,
    "order.cancelled.v1": OrderCancelledEvent,
    "order.saga_failed.v1": OrderSagaFailedEvent,
}


class UnknownFactTypeError(ValueError):
    """The envelope's `eventType` has no registered model."""

    code = "fact.unknown_type"


def parse_fact(data: str | bytes) -> FactEvent:
    """Parse one fact envelope: peek `eventType`, then validate against that fact's model."""
    document = json.loads(data)
    event_type = document.get("eventType") if isinstance(document, dict) else None
    model = FACT_MODELS.get(event_type) if isinstance(event_type, str) else None
    if model is None:
        raise UnknownFactTypeError(f"no model is registered for eventType {event_type!r}")
    return cast(FactEvent, from_wire_json(model, data))
