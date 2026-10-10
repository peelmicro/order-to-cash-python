"""`SimulatorCreditDecision`: the credit-check SIMULATOR bound in place of `AlwaysApprove`
(feature 20, R42 - R44, `billing_credit/design.md` 15.1).

A demo determinism device, not a credit policy: it makes the compensation path reproducible on
demand (an order whose total ends in `.99`) without a retailer whose credit is nearly exhausted.
It lives entirely behind `CreditDecisionPort`: no `domain/`, `application/` or `presentation/`
file changes (BC15).

Precedence (both rules could apply to one request): the `.99` rule is evaluated FIRST and, when it
matches, wins unconditionally, and the failure-rate draw is NOT consumed. R42 says "regardless of
the retailer's available credit" and, by the same intent, regardless of the draw: a `.99` amount
never surfaces as `simulated_failure_rate`. It reads ONLY the amount, never the available credit.

No I/O: `decide` is synchronous and runs inside the credit line's row lock (L24). The random source
is a plain callable returning a float in `[0, 1)`, injected so the failure-rate branch is
deterministic under test; the default is a private `random.Random()` instance (not the module's
shared state), seedable by passing `random.Random(seed).random`.

Money stays `int` minor units: `amount.amount % 100` is integer arithmetic. The failure rate is a
probability, not money, so a `float` is correct here.
"""

import math
import random
from collections.abc import Callable

from otc_billing.application.ports.credit_decision import (
    Approve,
    CreditDecision,
    CreditDecisionRequest,
    Refuse,
)
from otc_billing.domain.reasons import AdapterRejectionReason

CENTS_RULE_SUFFIX = 99


class SimulatorCreditDecision:
    def __init__(
        self, failure_rate: float, random_source: Callable[[], float] | None = None
    ) -> None:
        # NaN fails `0 <= x <= 1` too, but the finiteness check names the claim
        if not (math.isfinite(failure_rate) and 0 <= failure_rate <= 1):
            raise ValueError(
                f"failure_rate must be a number in the closed interval [0, 1]; got {failure_rate!r}"
            )
        self._failure_rate = failure_rate
        default_source = random.Random().random  # noqa: S311
        self._random = random_source if random_source is not None else default_source

    def decide(self, request: CreditDecisionRequest) -> CreditDecision:
        # R42: first, unconditional, and the draw below is not consumed on this path
        if request.amount.amount % 100 == CENTS_RULE_SUFFIX:
            return Refuse(AdapterRejectionReason.SIMULATED_CENTS_RULE)
        # R43: strict `<` on a draw in [0, 1): rate 0 never fires, rate 1 always does
        if self._random() < self._failure_rate:
            return Refuse(AdapterRejectionReason.SIMULATED_FAILURE_RATE)
        return Approve()
