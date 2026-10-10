"""The credit-decision port: feature 20's seam (`design.md` 7.4).

The ordering is the guarantee (BC13): the aggregate decides `over_limit` first, and this port is
consulted ONLY for a hold that fits. Its reason type cannot express `over_limit`
(`AdapterRejectionReason` has the two simulator members only, BC14), so an adapter can narrow
approvals and never widen them.

`decide` is a plain `def`, NOT `async def`: the call runs INSIDE the line's row lock, and a
synchronous signature makes "no I/O is awaited while the lock is held" structural (L24). A mypy
error, not a convention, is what stops an `async` adapter.
"""

from dataclasses import dataclass
from typing import Protocol

from otc_billing.domain.reasons import AdapterRejectionReason
from otc_shared_kernel import Money


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditDecisionRequest:
    """What the adapter may read: the order, the line's codes, the amount and the available credit
    BEFORE the hold."""

    order_reference: str
    retailer_code: str
    company_code: str
    credit_code: str
    amount: Money
    available_credit: Money


@dataclass(frozen=True, slots=True)
class Approve:
    pass


@dataclass(frozen=True, slots=True)
class Refuse:
    reason: AdapterRejectionReason


type CreditDecision = Approve | Refuse


class CreditDecisionPort(Protocol):
    def decide(self, request: CreditDecisionRequest) -> CreditDecision: ...
