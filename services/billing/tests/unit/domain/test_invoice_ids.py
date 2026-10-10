"""Every id on the invoice path is the one the id source supplied (task B6; BI34).

Sites in `Invoice`: the invoice id, each line id (one call site, called once per line), the
`InvoiceIssued` `event_id` and the `PaymentReceived` `event_id`. One assertion per site, each on
its own line, so a site that mints its own id (`UniqueId.new()`) fails at ITS assertion and nowhere
else (#8 id 49 guarded one of four sites; #9 feature 17 recurred it). The queue is consumed in the
documented order: invoice id, line ids in the request's order, the fact's id.

Loop scope: nothing here is async.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from otc_billing.domain.invoice import (
    Invoice,
    InvoiceContext,
    IssueInvoiceInput,
    IssueLineInput,
    PaymentInput,
    PaymentSource,
)
from otc_billing.domain.invoice_events import InvoiceIssued, PaymentReceived
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId

WHEN = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)


def uid(number: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{number:012x}"))


def id_source(supplied: Sequence[UniqueId]) -> Callable[[], UniqueId]:
    queue = list(supplied)

    def new_id() -> UniqueId:
        assert queue, "the aggregate asked for more identifiers than the test supplied"
        return queue.pop(0)

    return new_id


def test_bi34_every_invoice_line_and_event_id_is_the_one_the_id_source_supplied() -> None:
    context = InvoiceContext(occurred_at=WHEN, causation_id=uid(0xD0))
    data = IssueInvoiceInput(
        invoice_reference=InvoiceReference.from_sequence(321),
        order_reference="ORD-000101",
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        currency="EUR",
        lines=(
            IssueLineInput(product_code="PRD-ZZ", units=Quantity(3), unit_price=Money(1999, "EUR")),
            IssueLineInput(product_code="PRD-AA", units=Quantity(2), unit_price=Money(1234, "EUR")),
        ),
        discount=Money(350, "EUR"),
        correlation_id=uid(0xC0),
    )
    invoice = Invoice.issue(data, context, id_source([uid(0xA1), uid(0xA2), uid(0xA3), uid(0xA4)]))
    assert len(invoice.domain_events) == 1, "BI34: expected exactly one raised event"
    issued = invoice.domain_events[0]
    assert isinstance(issued, InvoiceIssued)
    assert invoice.id == uid(0xA1), "site 1: the invoice id is not the supplied one"
    assert invoice.lines[0].line_id == uid(0xA2), (
        "site 2: the first line id is not the supplied one"
    )
    assert invoice.lines[1].line_id == uid(0xA3), (
        "site 2: the second line id is not the supplied one"
    )
    assert issued.event_id == uid(0xA4), (
        "site 3: the InvoiceIssued event id is not the supplied one"
    )
    assert issued.aggregate_id == uid(0xA1), "the fact is about the invoice the source named"

    payment = PaymentInput(
        payment_reference="PAY-77-ABC",
        amount=Money(8115, "EUR"),
        value_date=WHEN,
        source=PaymentSource.ROBOT,
        correlation_id=uid(0xC0),
    )
    received = invoice.mark_paid(payment, context, id_source([uid(0xB1)]))
    assert isinstance(received, PaymentReceived)
    assert received.event_id == uid(0xB1), (
        "site 4: the PaymentReceived event id is not the supplied one"
    )
