"""The seven notify commands (`domain-model.md` 7.3): one per notified fact.

Each carries the fact's own typed event (the whole envelope, parsed by the generated model), so no
envelope field is copied by hand anywhere (#8 id 58: the hand copy of `correlationId` in #8's
consumer was unguarded). Messages subclass `otc_cqrs.Command[R]`, the registry's closed universe.
"""

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
from otc_cqrs import Command


@dataclass(frozen=True, slots=True)
class NotifyOrderPlacedCommand(Command[None]):
    event: OrderPlacedEvent


@dataclass(frozen=True, slots=True)
class NotifyOrderConfirmedCommand(Command[None]):
    event: OrderConfirmedEvent


@dataclass(frozen=True, slots=True)
class NotifyOrderDespatchedCommand(Command[None]):
    event: OrderDespatchedEvent


@dataclass(frozen=True, slots=True)
class NotifyInvoiceIssuedCommand(Command[None]):
    event: InvoiceIssuedEvent


@dataclass(frozen=True, slots=True)
class NotifyPaymentReceivedCommand(Command[None]):
    event: PaymentReceivedEvent


@dataclass(frozen=True, slots=True)
class NotifyOrderCompletedCommand(Command[None]):
    event: OrderCompletedEvent


@dataclass(frozen=True, slots=True)
class NotifyOrderCancelledCommand(Command[None]):
    event: OrderCancelledEvent
