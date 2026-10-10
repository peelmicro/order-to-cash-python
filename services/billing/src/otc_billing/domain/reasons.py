"""The reasons a credit hold is refused and a hold is released (`design.md` 5.4).

`AdapterRejectionReason` has the two simulator members ONLY: `over_limit` is the aggregate's word
and only the aggregate may say it (`BC14`, L24). `to_rejection_reason` is the one total mapping to
the fact's reason, a `match` with one arm per member ending in `assert_never`, so a third adapter
reason is a `mypy --strict` error until it is mapped. Plain `Enum`s with written-out tokens.
"""

from enum import Enum
from typing import assert_never


class CreditRejectionReason(Enum):
    OVER_LIMIT = "over_limit"
    SIMULATED_CENTS_RULE = "simulated_cents_rule"
    SIMULATED_FAILURE_RATE = "simulated_failure_rate"


class AdapterRejectionReason(Enum):
    SIMULATED_CENTS_RULE = "simulated_cents_rule"
    SIMULATED_FAILURE_RATE = "simulated_failure_rate"


class CreditReleaseReason(Enum):
    INVOICE_PAID = "invoice_paid"
    ORDER_CANCELLED = "order_cancelled"


def to_rejection_reason(reason: AdapterRejectionReason) -> CreditRejectionReason:
    match reason:
        case AdapterRejectionReason.SIMULATED_CENTS_RULE:
            return CreditRejectionReason.SIMULATED_CENTS_RULE
        case AdapterRejectionReason.SIMULATED_FAILURE_RATE:
            return CreditRejectionReason.SIMULATED_FAILURE_RATE
        case _:
            assert_never(reason)
