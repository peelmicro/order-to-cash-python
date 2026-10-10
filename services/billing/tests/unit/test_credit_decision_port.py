"""The credit-decision port's reason type (task C2; BC14's type half, L24).

`AdapterRejectionReason` has exactly the two simulator members and a total mapping to the fact's
reason; `over_limit` is the aggregate's word and is not a member. The other half of the guarantee
(an `OVER_LIMIT` member is a `mypy --strict` error through `assert_never`, and an `async` adapter is
a `mypy` error against the `Protocol`) is armed in `progress/impl_billing_credit.md`.

Loop scope: nothing here is async.
"""

from otc_billing.application.ports.credit_decision import (
    Approve,
    CreditDecision,
    CreditDecisionPort,
    CreditDecisionRequest,
    Refuse,
)
from otc_billing.domain.reasons import (
    AdapterRejectionReason,
    CreditRejectionReason,
    to_rejection_reason,
)
from otc_shared_kernel import Money


def test_bc14_the_adapter_reason_type_has_exactly_the_two_simulator_members_and_a_total_mapping() -> (  # noqa: E501
    None
):
    members = {member.value for member in AdapterRejectionReason}
    assert members == {"simulated_cents_rule", "simulated_failure_rate"}, (
        f"BC14: the adapter's reason type has members {sorted(members)}"
    )
    assert "over_limit" not in members
    assert len(AdapterRejectionReason) == 2
    mapped = {member: to_rejection_reason(member) for member in AdapterRejectionReason}
    assert mapped == {
        AdapterRejectionReason.SIMULATED_CENTS_RULE: CreditRejectionReason.SIMULATED_CENTS_RULE,
        AdapterRejectionReason.SIMULATED_FAILURE_RATE: (
            CreditRejectionReason.SIMULATED_FAILURE_RATE
        ),
    }
    assert CreditRejectionReason.OVER_LIMIT not in mapped.values()


def test_a_synchronous_adapter_satisfies_the_port_and_both_decisions_are_values() -> None:
    class Refusing:
        def decide(self, request: CreditDecisionRequest) -> CreditDecision:
            return Refuse(AdapterRejectionReason.SIMULATED_CENTS_RULE)

    port: CreditDecisionPort = Refusing()
    request = CreditDecisionRequest(
        order_reference="ORD-000101",
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        credit_code="CR-000321",
        amount=Money(250, "EUR"),
        available_credit=Money(700, "EUR"),
    )
    assert port.decide(request) == Refuse(AdapterRejectionReason.SIMULATED_CENTS_RULE)
    assert Approve() == Approve()
