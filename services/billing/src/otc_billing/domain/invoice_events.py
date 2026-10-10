"""The two facts of the `Invoice` aggregate: `invoice.issued.v1` and `payment.received.v1`
(`design.md` 5.6; `domain-model.md` 7.2 names `Invoice` as the producer of facts 10 and 11).

Domain types only, never `otc_contracts` models: mapping to the wire envelope is
`infrastructure/outbox/payloads.py`. Frozen, slotted, keyword-only. `aggregate_id` is the INVOICE's
id, `correlation_id` the order id, `causation_id` the request id. Amounts are integer minor units.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar

from otc_shared_kernel import InvoiceReference, UniqueId


class PaymentSource(Enum):
    """Where a payment came from (`PaymentSource` of `asyncapi.yaml`); tokens written out."""

    OPERATOR = "operator"
    ROBOT = "robot"
    TEST = "test"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceFactLine:
    product_code: str
    units: int
    unit_price: int


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceEventBase:
    event_id: UniqueId
    aggregate_id: UniqueId
    correlation_id: UniqueId
    causation_id: UniqueId
    occurred_at: datetime
    order_reference: str
    invoice_reference: InvoiceReference


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceIssued(InvoiceEventBase):
    EVENT_TYPE: ClassVar[str] = "invoice.issued.v1"

    invoice_date: datetime
    retailer_code: str
    company_code: str
    currency: str
    lines: tuple[InvoiceFactLine, ...]
    amount: int
    discount: int
    total_amount: int


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentReceived(InvoiceEventBase):
    EVENT_TYPE: ClassVar[str] = "payment.received.v1"

    payment_reference: str
    amount: int
    currency: str
    value_date: datetime
    source: PaymentSource


type InvoiceEvent = InvoiceIssued | PaymentReceived
