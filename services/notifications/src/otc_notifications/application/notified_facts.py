"""`NOTIFIED_FACTS`: the notified-fact filter, and the routing, in ONE dictionary.

The seven `eventType`s of `domain-model.md` 7.3 are the dictionary's KEYS: the filter and the
routing cannot drift apart because there is no second enumeration (#8's first review found the
handler guards ran past a separate filter and never crossed it: deleting five of seven entries
left its suite green). Anything not a key is acknowledged without a ledger row, a render or a
send: the `stock.*` and `credit.*` facts (internal saga mechanics, not events a counterparty is
told about) and `order.saga_failed.v1` (purely diagnostic).

Routing is on `envelope.eventType`, never on the topic: a topic carries facts of several types.
"""

from collections.abc import Callable
from dataclasses import dataclass

from otc_contracts.generated.asyncapi import (
    InvoiceIssuedEvent,
    OrderCancelledEvent,
    OrderCompletedEvent,
    OrderConfirmedEvent,
    OrderDespatchedEvent,
    OrderPlacedEvent,
    PaymentReceivedEvent,
)
from otc_contracts.wire import WireModel
from otc_cqrs import Command
from otc_notifications.application.messages import (
    NotifyInvoiceIssuedCommand,
    NotifyOrderCancelledCommand,
    NotifyOrderCompletedCommand,
    NotifyOrderConfirmedCommand,
    NotifyOrderDespatchedCommand,
    NotifyOrderPlacedCommand,
    NotifyPaymentReceivedCommand,
)


@dataclass(frozen=True, slots=True)
class NotifiedFact:
    """The model that parses the whole envelope, and the command that carries the parsed event."""

    event_model: type[WireModel]
    command: Callable[..., Command[None]]  # called as `command(event=<parsed event>)`


NOTIFIED_FACTS: dict[str, NotifiedFact] = {
    "order.placed.v1": NotifiedFact(OrderPlacedEvent, NotifyOrderPlacedCommand),
    "order.confirmed.v1": NotifiedFact(OrderConfirmedEvent, NotifyOrderConfirmedCommand),
    "order.despatched.v1": NotifiedFact(OrderDespatchedEvent, NotifyOrderDespatchedCommand),
    "invoice.issued.v1": NotifiedFact(InvoiceIssuedEvent, NotifyInvoiceIssuedCommand),
    "payment.received.v1": NotifiedFact(PaymentReceivedEvent, NotifyPaymentReceivedCommand),
    "order.completed.v1": NotifiedFact(OrderCompletedEvent, NotifyOrderCompletedCommand),
    "order.cancelled.v1": NotifiedFact(OrderCancelledEvent, NotifyOrderCancelledCommand),
}
