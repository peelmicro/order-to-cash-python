"""`invoice_mapper`: rows <-> snapshots (task D4; BI10, BI24, BI27; ledger L15, L16, L17, L22).

No database: the mapped classes are constructed and read without a session. Every value is distinct
from every other: the unit price (1999) is neither the line total (3 x 1999 = 5997) nor the invoice
amount (8465) nor the total (8115); the discount is 350; `created_at` differs from `invoice_date`
and from `paid_at`.

Loop scope: nothing here is async.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from otc_billing.domain.invoice import (
    Invoice,
    InvoiceContext,
    IssueInvoiceInput,
    IssueLineInput,
    PaymentInput,
)
from otc_billing.domain.invoice_errors import InvalidInvoiceSnapshotError, UnknownInvoiceStatusError
from otc_billing.domain.invoice_events import PaymentSource
from otc_billing.domain.invoice_state import InvoiceStatus, Issued, Paid
from otc_billing.infrastructure.persistence import invoice_mapper
from otc_billing.infrastructure.persistence.models import Invoice as InvoiceRow
from otc_billing.infrastructure.persistence.models import InvoiceItem as InvoiceItemRow
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId

INVOICE_DATE = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)
CREATED_AT = INVOICE_DATE + timedelta(seconds=7)
PAID_AT = INVOICE_DATE + timedelta(days=3, minutes=11)


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def issued_invoice() -> Invoice:
    queue = [uid(0xA1), uid(0xA2), uid(0xA3), uid(0xA4)]
    return Invoice.issue(
        IssueInvoiceInput(
            invoice_reference=InvoiceReference.from_sequence(321),
            order_reference="ORD-000101",
            retailer_code="RETAIL-77",
            company_code="SUPPLY-CO",
            currency="EUR",
            lines=(
                IssueLineInput(
                    product_code="PRD-ZZ", units=Quantity(3), unit_price=Money(1999, "EUR")
                ),
                IssueLineInput(
                    product_code="PRD-AA", units=Quantity(2), unit_price=Money(1234, "EUR")
                ),
            ),
            discount=Money(350, "EUR"),
            correlation_id=uid(0xC0),
        ),
        InvoiceContext(occurred_at=INVOICE_DATE, causation_id=uid(0xD0)),
        lambda: queue.pop(0),
    )


def header_row(*, status: object = "issued", paid_at: datetime | None = None) -> InvoiceRow:
    return InvoiceRow(
        id=uuid.UUID(int=0xA1),
        invoice_reference="INV-000321",
        invoice_date=INVOICE_DATE,
        company_code="SUPPLY-CO",
        retailer_code="RETAIL-77",
        order_reference="ORD-000101",
        amount=8465,
        discount=350,
        total_amount=8115,
        currency_code="EUR",
        status=status,
        paid_at=paid_at,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def item_rows() -> list[InvoiceItemRow]:
    # stored in an order that is neither the request's nor the canonical one
    return [
        InvoiceItemRow(
            id=uuid.UUID(int=0xA9),
            invoice_id=uuid.UUID(int=0xA1),
            product_code="PRD-ZZ",
            units=3,
            price=1999,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        ),
        InvoiceItemRow(
            id=uuid.UUID(int=0xA3),
            invoice_id=uuid.UUID(int=0xA1),
            product_code="PRD-AA",
            units=2,
            price=1234,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        ),
    ]


def test_a_row_maps_to_a_snapshot_field_by_field_with_lines_in_canonical_order() -> None:
    snapshot = invoice_mapper.invoice_snapshot(header_row(), item_rows())

    assert snapshot.id == uid(0xA1)
    assert snapshot.invoice_reference.value == "INV-000321"
    assert snapshot.invoice_date == INVOICE_DATE
    assert snapshot.order_reference == "ORD-000101"
    assert snapshot.retailer_code == "RETAIL-77"
    assert snapshot.company_code == "SUPPLY-CO"
    assert snapshot.currency == "EUR"
    assert snapshot.amount == Money(8465, "EUR")
    assert snapshot.discount == Money(350, "EUR")
    assert snapshot.total_amount == Money(8115, "EUR")
    assert snapshot.state == Issued()
    assert [(ln.product_code, ln.units.value, ln.unit_price.amount) for ln in snapshot.lines] == [
        ("PRD-AA", 2, 1234),
        ("PRD-ZZ", 3, 1999),
    ], "L15: the reload is not in canonical (product_code, id) order"
    assert [ln.id for ln in snapshot.lines] == [uid(0xA3), uid(0xA9)]
    # the aggregate rehydrates from it (the totals agree with the lines)
    assert Invoice.rehydrate(snapshot).total_amount == Money(8115, "EUR")


def test_a_paid_row_maps_to_the_paid_state_and_the_view_carries_the_instant() -> None:
    row = header_row(status="paid", paid_at=PAID_AT)
    snapshot = invoice_mapper.invoice_snapshot(row, item_rows())
    assert snapshot.state == Paid(PAID_AT)
    view = invoice_mapper.invoice_view(row)
    assert view.status is InvoiceStatus.PAID
    assert view.paid_at == PAID_AT
    assert (view.amount, view.discount, view.total_amount) == (8465, 350, 8115)
    issued_view = invoice_mapper.invoice_view(header_row())
    assert issued_view.status is InvoiceStatus.ISSUED
    assert issued_view.paid_at is None


def test_a_row_whose_status_and_paid_at_disagree_or_whose_token_is_unknown_is_refused() -> None:
    for status, paid_at in (("paid", None), ("issued", PAID_AT)):
        with pytest.raises(InvalidInvoiceSnapshotError) as caught:
            invoice_mapper.invoice_snapshot(header_row(status=status, paid_at=paid_at), item_rows())
        assert "INV-000321" in caught.value.message, "BI10: the error does not name the invoice"
        with pytest.raises(InvalidInvoiceSnapshotError):
            invoice_mapper.invoice_view(header_row(status=status, paid_at=paid_at))
    with pytest.raises(UnknownInvoiceStatusError):
        invoice_mapper.invoice_snapshot(header_row(status="Paid", paid_at=PAID_AT), item_rows())


def test_new_rows_mirror_the_aggregate_with_the_unit_price_and_updated_at_equal_to_created_at() -> (
    None
):
    invoice = issued_invoice()
    header = invoice_mapper.new_invoice_row(invoice, CREATED_AT)
    assert header.id == uuid.UUID(int=0xA1)
    assert header.invoice_reference == "INV-000321"
    assert header.invoice_date == INVOICE_DATE
    assert header.company_code == "SUPPLY-CO"
    assert header.retailer_code == "RETAIL-77"
    assert header.order_reference == "ORD-000101"
    assert (header.amount, header.discount, header.total_amount) == (8465, 350, 8115)
    assert header.currency_code == "EUR"
    assert header.status == "issued"
    assert header.paid_at is None
    assert header.created_at == CREATED_AT
    assert header.updated_at == header.created_at, "a new row's updated_at must equal created_at"

    items = [invoice_mapper.new_item_row(ln, invoice.id, CREATED_AT) for ln in invoice.lines]
    assert [(i.product_code, i.units, i.price) for i in items] == [
        ("PRD-ZZ", 3, 1999),
        ("PRD-AA", 2, 1234),
    ], "price must be the UNIT price (not the line total 5997 / 2468)"
    assert [i.id for i in items] == [uuid.UUID(int=0xA2), uuid.UUID(int=0xA3)]
    assert {i.invoice_id for i in items} == {uuid.UUID(int=0xA1)}
    assert all(i.updated_at == i.created_at == CREATED_AT for i in items)


def test_status_and_paid_at_are_written_from_the_one_state_of_a_paid_invoice() -> None:
    invoice = issued_invoice()
    invoice.mark_paid(
        PaymentInput(
            payment_reference="PAY-77-ABC",
            amount=Money(8115, "EUR"),
            value_date=PAID_AT - timedelta(hours=5),
            source=PaymentSource.ROBOT,
            correlation_id=uid(0xC0),
        ),
        InvoiceContext(occurred_at=PAID_AT, causation_id=uid(0xD0)),
        lambda: uid(0xB0),
    )
    header = invoice_mapper.new_invoice_row(invoice, CREATED_AT)
    assert header.status == "paid", "a paid invoice must write the lower-case token 'paid'"
    assert header.paid_at == PAID_AT, "paid_at must be written from the same state"
