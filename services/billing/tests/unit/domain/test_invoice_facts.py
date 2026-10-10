"""`invoice.issued.v1` provenance (task B8; BI13): the stamped values ARE the supplied ones.

The id source and the clock are injected with known, pairwise-distinct values and every stamped
field is compared by equality with the value the test supplied -- never "non-default and distinct".

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
)
from otc_billing.domain.invoice_events import InvoiceFactLine, InvoiceIssued
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId

CLOCK = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)


def uid(number: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{number:012x}"))


def id_source(supplied: Sequence[UniqueId]) -> Callable[[], UniqueId]:
    queue = list(supplied)

    def new_id() -> UniqueId:
        assert queue, "the aggregate asked for more identifiers than the test supplied"
        return queue.pop(0)

    return new_id


def test_bi13_stamps_invoice_issued_from_the_supplied_ids_clock_and_headers() -> None:
    order_id = uid(0xC0)  # x-correlation-id
    request_id = uid(0xD0)  # x-request-id
    data = IssueInvoiceInput(
        invoice_reference=InvoiceReference.from_sequence(777),
        order_reference="ORD-000101",
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        currency="EUR",
        lines=(  # request order: NOT canonical (PRD-ZZ sorts after PRD-AA)
            IssueLineInput(product_code="PRD-ZZ", units=Quantity(3), unit_price=Money(1999, "EUR")),
            IssueLineInput(product_code="PRD-AA", units=Quantity(2), unit_price=Money(1234, "EUR")),
        ),
        discount=Money(350, "EUR"),
        correlation_id=order_id,
    )
    invoice = Invoice.issue(
        data,
        InvoiceContext(occurred_at=CLOCK, causation_id=request_id),
        id_source([uid(0xA1), uid(0xA2), uid(0xA3), uid(0xA4)]),
    )

    assert len(invoice.domain_events) == 1, "BI13: expected exactly one raised event"
    fact = invoice.domain_events[0]
    assert isinstance(fact, InvoiceIssued)
    # the envelope identity
    assert fact.aggregate_id == uid(0xA1), "aggregate_id must be the invoice's own id"
    assert fact.correlation_id == order_id, "correlation_id must be the order id (x-correlation-id)"
    assert fact.causation_id == request_id, "causation_id must be the request id (x-request-id)"
    assert fact.event_id == uid(0xA4)
    assert fact.occurred_at == CLOCK
    assert fact.invoice_date == CLOCK
    assert invoice.invoice_date == CLOCK
    assert len({fact.aggregate_id, fact.correlation_id, fact.causation_id, fact.event_id}) == 4
    # the payload: every field equals the supplied value, lines in the REQUEST's order
    assert fact.order_reference == "ORD-000101"
    assert fact.invoice_reference.value == "INV-000777"
    assert fact.retailer_code == "RETAIL-77"
    assert fact.company_code == "SUPPLY-CO"
    assert fact.currency == "EUR"
    assert fact.lines == (
        InvoiceFactLine(product_code="PRD-ZZ", units=3, unit_price=1999),
        InvoiceFactLine(product_code="PRD-AA", units=2, unit_price=1234),
    )
    assert (fact.amount, fact.discount, fact.total_amount) == (8465, 350, 8115)
