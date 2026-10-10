"""The adapter bound until feature 20 (task C2; BC15).

Loop scope: nothing here is async.
"""

from otc_billing.application.ports.credit_decision import (
    Approve,
    CreditDecisionPort,
    CreditDecisionRequest,
)
from otc_billing.infrastructure.credit.always_approve import AlwaysApproveCreditDecision
from otc_shared_kernel import Money


def test_bc15_approves_every_request() -> None:
    # typed against the port on purpose: an `async def decide` is a mypy error HERE (L24)
    port: CreditDecisionPort = AlwaysApproveCreditDecision()
    for amount, available in ((0, 0), (1, 1), (250, 700), (700, 700), (701, 700), (99, 5)):
        decision = port.decide(
            CreditDecisionRequest(
                order_reference="ORD-000101",
                retailer_code="RETAIL-77",
                company_code="SUPPLY-CO",
                credit_code="CR-000321",
                amount=Money(amount, "EUR"),
                available_credit=Money(available, "EUR"),
            )
        )
        assert decision == Approve(), f"BC15: the default adapter did not approve {amount}"
