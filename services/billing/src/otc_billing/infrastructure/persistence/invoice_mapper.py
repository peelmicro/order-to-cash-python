"""Rows <-> snapshots, and the ONLY constructor of `Invoice` / `InvoiceItem` rows
(`design.md` 9.2; ledger L15, L16, L17, L22, L23).

* `status` and `paid_at` are ONE value in the domain and TWO columns in the table; this module is
  the one place they meet. Reading, `parse_invoice_state(row.status, row.paid_at)` is the only
  combiner and it refuses a disagreeing or unknown pair, so a bad row cannot even become a
  snapshot. Writing, both columns are derived from the one `state` (`state_token(...).value` and
  `paid_at_of(...)`), so they cannot disagree on the way out.
* `invoice_items.price` is the UNIT price (the seed writes `line.unit_price` into it); there is no
  per-line discount and no position column, so a reload's line order is canonical
  `(product_code, line id)`, sorted here in PYTHON, never by the database's collation.
* Instants are kept exactly as asyncpg returned them (an aware UTC `datetime` or `None`): this
  module neither attaches nor converts a zone, and a `NULL` `paid_at` is never mapped to another
  value.
* Ids are rebuilt as plain `uuid.UUID` (asyncpg hands back its own subclass, which `UniqueId`
  refuses).
* Rows are constructed through the mapped classes so the ORM range guard fires on `units` and
  `price` at assignment; `updated_at` is written equal to `created_at` (feature 22's `mark_paid`
  update moves it).
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from otc_billing.application.messages import InvoiceViewData
from otc_billing.domain.invoice import Invoice, InvoiceLine
from otc_billing.domain.invoice_events import PaymentSource
from otc_billing.domain.invoice_snapshot import (
    InvoiceLineSnapshot,
    InvoiceSnapshot,
    PaymentSnapshot,
)
from otc_billing.domain.invoice_state import paid_at_of, parse_invoice_state, state_token
from otc_billing.infrastructure.persistence.models import Invoice as InvoiceRow
from otc_billing.infrastructure.persistence.models import InvoiceItem as InvoiceItemRow
from otc_billing.infrastructure.persistence.models import Payment as PaymentRow
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId


def _unique_id(value: UUID) -> UniqueId:
    """asyncpg hands back its own `UUID` subclass (`asyncpg.pgproto.pgproto.UUID`), which the
    domain's `type(...) is uuid.UUID` check refuses; rebuild a plain `uuid.UUID`."""
    return UniqueId(UUID(int=value.int))


def line_order_key(line: InvoiceLineSnapshot) -> tuple[str, int]:
    """The canonical line order: exact product code (code-point order), then the line id."""
    return (line.product_code, line.id.value.int)


def invoice_snapshot(row: InvoiceRow, items: Sequence[InvoiceItemRow]) -> InvoiceSnapshot:
    currency = row.currency_code
    lines = sorted(
        (
            InvoiceLineSnapshot(
                id=_unique_id(item.id),
                product_code=item.product_code,
                units=Quantity(item.units),
                unit_price=Money(item.price, currency),
            )
            for item in items
        ),
        key=line_order_key,
    )
    return InvoiceSnapshot(
        id=_unique_id(row.id),
        invoice_reference=InvoiceReference(row.invoice_reference),
        invoice_date=row.invoice_date,
        order_reference=row.order_reference,
        retailer_code=row.retailer_code,
        company_code=row.company_code,
        currency=currency,
        lines=tuple(lines),
        amount=Money(row.amount, currency),
        discount=Money(row.discount, currency),
        total_amount=Money(row.total_amount, currency),
        state=parse_invoice_state(row.status, row.paid_at, invoice_reference=row.invoice_reference),
    )


def invoice_view(row: InvoiceRow) -> InvoiceViewData:
    """One row of `billing.invoice.list`: no lines (`InvoiceView` carries none)."""
    state = parse_invoice_state(row.status, row.paid_at, invoice_reference=row.invoice_reference)
    return InvoiceViewData(
        invoice_id=_unique_id(row.id),
        invoice_reference=row.invoice_reference,
        invoice_date=row.invoice_date,
        order_reference=row.order_reference,
        retailer_code=row.retailer_code,
        company_code=row.company_code,
        currency=row.currency_code,
        amount=row.amount,
        discount=row.discount,
        total_amount=row.total_amount,
        status=state_token(state),
        paid_at=paid_at_of(state),
    )


def new_invoice_row(invoice: Invoice, created_at: datetime) -> InvoiceRow:
    return InvoiceRow(
        id=invoice.id.value,
        invoice_reference=invoice.invoice_reference.value,
        invoice_date=invoice.invoice_date,
        company_code=invoice.company_code,
        retailer_code=invoice.retailer_code,
        order_reference=invoice.order_reference,
        amount=invoice.amount.amount,
        discount=invoice.discount.amount,
        total_amount=invoice.total_amount.amount,
        currency_code=invoice.currency,
        status=state_token(invoice.state).value,
        paid_at=paid_at_of(invoice.state),
        created_at=created_at,
        updated_at=created_at,
    )


def new_item_row(line: InvoiceLine, invoice_id: UniqueId, created_at: datetime) -> InvoiceItemRow:
    return InvoiceItemRow(
        id=line.line_id.value,
        invoice_id=invoice_id.value,
        product_code=line.product_code,
        units=line.units.value,
        price=line.unit_price.amount,
        created_at=created_at,
        updated_at=created_at,
    )


def payment_snapshot(row: PaymentRow) -> PaymentSnapshot:
    """A stored remittance; `currency` is the row's own (the payment's, not assumed to be the
    invoice's: a mismatching one is never stored)."""
    return PaymentSnapshot(
        id=_unique_id(row.id),
        payment_reference=row.payment_reference,
        invoice_id=_unique_id(row.invoice_id),
        amount=Money(row.amount, row.currency_code),
        value_date=row.value_date,
        source=PaymentSource(row.source),
    )


def new_payment_row(payment: PaymentSnapshot, created_at: datetime) -> PaymentRow:
    return PaymentRow(
        id=payment.id.value,
        payment_reference=payment.payment_reference,
        invoice_id=payment.invoice_id.value,
        amount=payment.amount.amount,
        currency_code=payment.amount.currency,
        value_date=payment.value_date,
        source=payment.source.value,
        created_at=created_at,
    )
