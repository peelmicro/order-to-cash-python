"""The three facts of the Billing service: `credit.approved.v1`, `credit.rejected.v1` and
`credit.released.v1` (`design.md` 5.4).

Domain types only (`UniqueId`, `str`, `int`, `datetime`), never `otc_contracts` models: mapping to
the wire envelope is `infrastructure/outbox/payloads.py`. Frozen, slotted, keyword-only. Every
identity field of the payload (`order_reference`, `retailer_code`, `company_code`, `credit_code`,
`currency`) comes from the RESOLVED credit line, never from the request (`BC28`). Amounts are
integer minor units.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from otc_billing.domain.reasons import CreditRejectionReason, CreditReleaseReason
from otc_shared_kernel import UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditEventBase:
    event_id: UniqueId
    aggregate_id: UniqueId
    correlation_id: UniqueId
    causation_id: UniqueId
    occurred_at: datetime
    order_reference: str
    retailer_code: str
    company_code: str
    credit_code: str
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditApproved(CreditEventBase):
    EVENT_TYPE: ClassVar[str] = "credit.approved.v1"

    held_amount: int
    available_credit_after: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditRejected(CreditEventBase):
    EVENT_TYPE: ClassVar[str] = "credit.rejected.v1"

    requested_amount: int
    available_credit: int
    reason: CreditRejectionReason


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditReleased(CreditEventBase):
    EVENT_TYPE: ClassVar[str] = "credit.released.v1"

    released_amount: int
    available_credit_after: int
    reason: CreditReleaseReason


type CreditEvent = CreditApproved | CreditRejected | CreditReleased
