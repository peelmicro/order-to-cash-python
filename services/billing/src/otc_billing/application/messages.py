"""The messages of the Billing service and their results (`design.md` 7.1).

Messages subclass `otc_cqrs.Command[R]` / `Query[R]` (the registry's closed universe); results are
application dataclasses, never `otc_contracts` models: `presentation/credit_wire.py` maps them to
the wire. `HoldCreditCommand`, `ReleaseCreditCommand` and `IssueInvoiceCommand` carry
`correlation_id` (`x-correlation-id`) and `request_id` (`x-request-id`) as `UniqueId`s (BC1, BI2);
the list queries carry neither. Amounts are integer minor units, except the hold command's
`amount`, a `Money`.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from otc_billing.domain.invoice_events import PaymentSource
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_billing.domain.reasons import CreditRejectionReason
from otc_cqrs import Command, Query
from otc_shared_kernel import Money, UniqueId

# ----------------------------------------------------------------------------- credit.hold


class HoldOutcomeKind(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ALREADY_HELD = "already_held"


@dataclass(frozen=True, slots=True)
class HoldResult:
    """`approved` carries `held_amount` and no reason; `rejected` a reason and no `held_amount`;
    `already_held` the RECORDED `held_amount` and the CURRENT `available_credit` (BC7)."""

    outcome: HoldOutcomeKind
    order_reference: str
    credit_code: str
    currency: str
    held_amount: int | None
    available_credit: int
    reason: CreditRejectionReason | None


@dataclass(frozen=True, slots=True)
class HoldCreditCommand(Command[HoldResult]):
    order_reference: str
    retailer_code: str
    company_code: str
    amount: Money
    correlation_id: UniqueId
    request_id: UniqueId


# -------------------------------------------------------------------------- credit.release


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    """`released` False is a success (BC25): nothing outstanding, nothing written."""

    released: bool
    order_reference: str
    credit_code: str
    currency: str
    released_amount: int | None
    available_credit_after: int


@dataclass(frozen=True, slots=True)
class ReleaseCreditCommand(Command[ReleaseResult]):
    order_reference: str
    retailer_code: str
    company_code: str
    correlation_id: UniqueId
    request_id: UniqueId


# ----------------------------------------------------------------------------- credit.list


@dataclass(frozen=True, slots=True)
class CreditViewData:
    credit_code: str
    retailer_code: str
    company_code: str
    currency: str
    credit_limit: int
    active_holds: int
    open_exposure: int
    available_credit: int


@dataclass(frozen=True, slots=True)
class CreditPage:
    items: tuple[CreditViewData, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ListCreditQuery(Query[CreditPage]):
    page: int
    page_size: int
    retailer_code: str | None
    company_code: str | None


# --------------------------------------------------------------------------- invoice.issue


@dataclass(frozen=True, slots=True)
class IssueLine:
    product_code: str
    units: int
    unit_price: int


@dataclass(frozen=True, slots=True)
class InvoiceSummary:
    """The invoice as the issue reply names it: new or existing, with its CURRENT status (BI9)."""

    invoice_id: UniqueId
    invoice_reference: str
    invoice_date: datetime
    order_reference: str
    currency: str
    total_amount: int
    status: InvoiceStatus


@dataclass(frozen=True, slots=True)
class InvoiceIssueResult:
    """`created` False is a success (BI9): the existing invoice, nothing written."""

    created: bool
    invoice: InvoiceSummary


@dataclass(frozen=True, slots=True)
class IssueInvoiceCommand(Command[InvoiceIssueResult]):
    order_reference: str
    retailer_code: str
    company_code: str
    currency: str
    lines: tuple[IssueLine, ...]
    discount: int  # 0 when the request carries none
    correlation_id: UniqueId
    request_id: UniqueId


# -------------------------------------------------------------------------- invoice.list


@dataclass(frozen=True, slots=True)
class InvoiceViewData:
    invoice_id: UniqueId
    invoice_reference: str
    invoice_date: datetime
    order_reference: str
    retailer_code: str
    company_code: str
    currency: str
    amount: int
    discount: int
    total_amount: int
    status: InvoiceStatus
    paid_at: datetime | None


@dataclass(frozen=True, slots=True)
class InvoicePage:
    items: tuple[InvoiceViewData, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ListInvoicesQuery(Query[InvoicePage]):
    page: int
    page_size: int
    status: InvoiceStatus | None
    retailer_code: str | None
    company_code: str | None
    order_reference: str | None
    issued_before_minutes: int | None


# ------------------------------------------------------------------------ payment.register


class PaymentOutcome(Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class PaymentRegisterResult:
    """`duplicate` carries the stored invoice's CURRENT status and `paid_at`: the original
    outcome, nothing written (R48)."""

    outcome: PaymentOutcome
    payment_reference: str
    invoice_reference: str
    order_reference: str
    invoice_status: InvoiceStatus
    paid_at: datetime | None


@dataclass(frozen=True, slots=True)
class RegisterPaymentCommand(Command[PaymentRegisterResult]):
    invoice_id: UniqueId | None
    invoice_reference: str | None
    payment_reference: str
    amount: Money
    value_date: datetime
    source: PaymentSource
    correlation_id: UniqueId
    request_id: UniqueId
