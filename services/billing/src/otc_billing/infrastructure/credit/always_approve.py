"""`AlwaysApproveCreditDecision`: approves every request. Since feature 20 it is NOT the default
binding (`composition.py` binds `simulator.SimulatorCreditDecision`); it is kept for the tests that
want no simulation at all (`tests/integration/test_credit_repository.py` builds its scope with it).
Pure and synchronous (BC15).
"""

from otc_billing.application.ports.credit_decision import (
    Approve,
    CreditDecision,
    CreditDecisionRequest,
)


class AlwaysApproveCreditDecision:
    def decide(self, request: CreditDecisionRequest) -> CreditDecision:
        return Approve()
