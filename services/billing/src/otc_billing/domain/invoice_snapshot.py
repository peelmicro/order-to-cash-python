"""What `Invoice.rehydrate` takes and `to_snapshot` returns: a stored invoice as business values,
built by the repository's row mapper; keyword-constructed (`design.md` 2).

`state` is the ONE value that the table stores as `status` + `paid_at` (BI10). Row timestamps
(`created_at`, `updated_at`) are not here: they are the mapper's (the domain reads no clock). The
lines are a tuple; their order is whatever the builder chose (the aggregate keeps the request's
order, a reload is canonical `(product_code, id)`).
"""

from dataclasses import dataclass
from datetime import datetime

from otc_billing.domain.invoice_events import PaymentSource
from otc_billing.domain.invoice_state import InvoiceState
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceLineSnapshot:
    id: UniqueId
    product_code: str
    units: Quantity
    unit_price: Money


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceSnapshot:
    id: UniqueId
    invoice_reference: InvoiceReference
    invoice_date: datetime
    order_reference: str
    retailer_code: str
    company_code: str
    currency: str
    lines: tuple[InvoiceLineSnapshot, ...]
    amount: Money
    discount: Money
    total_amount: Money
    state: InvoiceState


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentSnapshot:
    """A stored remittance (`payments` row) as business values: what the idempotency decision
    (R48) compares a repeated request against. `payment_reference` is the key (B10)."""

    id: UniqueId
    payment_reference: str
    invoice_id: UniqueId
    amount: Money
    value_date: datetime
    source: PaymentSource
