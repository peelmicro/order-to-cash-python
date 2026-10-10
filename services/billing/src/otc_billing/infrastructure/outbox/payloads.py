"""Domain event -> wire fact: one function per event class, no arithmetic.

References and identifiers become their `.value`, enums their token, every instant goes through
`wire_instant` (OI19: the stored millisecond, the envelope's and the payload's are the same one).
Amounts are plain `int` minor units already; no `Decimal`, no `float`, no `/` on this path.

`narrow` is the single place an unknown event class is refused; `build_fact` then has one `match`
case per class (`assert_never` makes a sixth class a type error until it is mapped) and builds the
typed `Envelope[<payload model>]`. Feature 21 added the two invoice facts: `invoice.issued.v1` and
`payment.received.v1` (the latter has no caller until feature 22). The envelope is parametrised by
the CONCRETE payload class on purpose: pydantic serialises a field by its declared type, so
`Envelope[WireModel]` would write `{}`.

Service-specific, NOT a parity-guarded copy of Orders' module of the same name.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import assert_never

from otc_billing.domain.events import CreditApproved, CreditEvent, CreditRejected, CreditReleased
from otc_billing.domain.invoice_events import InvoiceEvent, InvoiceIssued, PaymentReceived
from otc_billing.infrastructure.outbox.errors import UnmappedDomainEventError
from otc_contracts import Envelope, WireModel, wire_instant
from otc_contracts.generated import asyncapi


@dataclass(frozen=True, slots=True)
class BuiltFact:
    """A typed envelope and the payload it carries (the payload's text is what the row stores)."""

    envelope: WireModel
    payload: WireModel
    occurred_at: datetime  # the envelope's `occurredAt`, whole milliseconds: what the row stores


type BillingEvent = CreditEvent | InvoiceEvent


def narrow(event: object) -> BillingEvent:
    match event:
        case (
            CreditApproved()
            | CreditRejected()
            | CreditReleased()
            | InvoiceIssued()
            | PaymentReceived()
        ):
            return event
        case _:
            raise UnmappedDomainEventError(type(event).__name__)


def approved_payload(event: CreditApproved) -> asyncapi.CreditApprovedPayload:
    return asyncapi.CreditApprovedPayload(
        order_reference=event.order_reference,
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        credit_code=event.credit_code,
        currency=event.currency,
        held_amount=event.held_amount,
        available_credit_after=event.available_credit_after,
    )


def rejected_payload(event: CreditRejected) -> asyncapi.CreditRejectedPayload:
    return asyncapi.CreditRejectedPayload(
        order_reference=event.order_reference,
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        credit_code=event.credit_code,
        currency=event.currency,
        requested_amount=event.requested_amount,
        available_credit=event.available_credit,
        reason=asyncapi.Reason2(event.reason.value),
    )


def released_payload(event: CreditReleased) -> asyncapi.CreditReleasedPayload:
    return asyncapi.CreditReleasedPayload(
        order_reference=event.order_reference,
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        credit_code=event.credit_code,
        currency=event.currency,
        released_amount=event.released_amount,
        available_credit_after=event.available_credit_after,
        reason=asyncapi.Reason3(event.reason.value),
    )


def issued_payload(event: InvoiceIssued) -> asyncapi.InvoiceIssuedPayload:
    return asyncapi.InvoiceIssuedPayload(
        order_reference=event.order_reference,
        invoice_reference=event.invoice_reference.value,
        invoice_date=wire_instant(event.invoice_date),
        retailer_code=event.retailer_code,
        company_code=event.company_code,
        currency=event.currency,
        lines=[
            asyncapi.InvoiceLine(
                product_code=line.product_code, units=line.units, unit_price=line.unit_price
            )
            for line in event.lines
        ],
        amount=event.amount,
        discount=event.discount,
        total_amount=event.total_amount,
    )


def payment_payload(event: PaymentReceived) -> asyncapi.PaymentReceivedPayload:
    return asyncapi.PaymentReceivedPayload(
        order_reference=event.order_reference,
        invoice_reference=event.invoice_reference.value,
        payment_reference=event.payment_reference,
        currency=event.currency,
        amount=event.amount,
        value_date=wire_instant(event.value_date),
        source=asyncapi.PaymentSource(event.source.value),
    )


def _envelope[P: WireModel](
    envelope_type: type[Envelope[P]], event: BillingEvent, payload: P, occurred_at: datetime
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


def build_fact(event: BillingEvent) -> BuiltFact:
    """The typed envelope of a (narrowed) domain event. The caller has run the R11 guard."""
    at = wire_instant(event.occurred_at)
    match event:
        case CreditApproved():
            approved = approved_payload(event)
            envelope: WireModel = _envelope(
                Envelope[asyncapi.CreditApprovedPayload], event, approved, at
            )
            return BuiltFact(envelope=envelope, payload=approved, occurred_at=at)
        case CreditRejected():
            rejected = rejected_payload(event)
            envelope = _envelope(Envelope[asyncapi.CreditRejectedPayload], event, rejected, at)
            return BuiltFact(envelope=envelope, payload=rejected, occurred_at=at)
        case CreditReleased():
            released = released_payload(event)
            envelope = _envelope(Envelope[asyncapi.CreditReleasedPayload], event, released, at)
            return BuiltFact(envelope=envelope, payload=released, occurred_at=at)
        case InvoiceIssued():
            issued = issued_payload(event)
            envelope = _envelope(Envelope[asyncapi.InvoiceIssuedPayload], event, issued, at)
            return BuiltFact(envelope=envelope, payload=issued, occurred_at=at)
        case PaymentReceived():
            payment = payment_payload(event)
            envelope = _envelope(Envelope[asyncapi.PaymentReceivedPayload], event, payment, at)
            return BuiltFact(envelope=envelope, payload=payment, occurred_at=at)
        case _:
            assert_never(event)
