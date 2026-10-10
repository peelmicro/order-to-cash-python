"""The credit-check simulator behind the port (feature 20; R42, R43, the unit halves).

Pure: no database, no broker, no clock. Randomness is always INJECTED, so no test is probabilistic
(the one default-source test uses rates 0 and 1, which no draw in [0, 1) can disagree with). Every
fixture value is pairwise distinct; the amounts that must not fire (98, 100, 4200, ...) and those
that must (99, 4299, ...) share no suffix by accident.

Loop scope: nothing here is async (`decide` is synchronous, L24).
"""

import inspect
import random

import pytest

from otc_billing.application.ports.credit_decision import (
    Approve,
    CreditDecision,
    CreditDecisionPort,
    CreditDecisionRequest,
    Refuse,
)
from otc_billing.domain.reasons import AdapterRejectionReason
from otc_billing.infrastructure.credit.simulator import SimulatorCreditDecision
from otc_shared_kernel import Money

CENTS = Refuse(AdapterRejectionReason.SIMULATED_CENTS_RULE)
RATE = Refuse(AdapterRejectionReason.SIMULATED_FAILURE_RATE)


def request(amount: int, available: int = 1_000_000) -> CreditDecisionRequest:
    return CreditDecisionRequest(
        order_reference="ORD-000101",
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        credit_code="CR-000321",
        amount=Money(amount, "EUR"),
        available_credit=Money(available, "EUR"),
    )


class Draws:
    """A random source that returns a fixed value and counts how often it was asked."""

    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.value


@pytest.mark.parametrize("available", [0, 1, 4299, 4300, 500_000, 9_223_372_036_854_775_807])
def test_r42_an_amount_ending_in_99_is_refused_with_the_cents_rule_whatever_the_available_credit(
    available: int,
) -> None:
    port: CreditDecisionPort = SimulatorCreditDecision(0.0, Draws(0.5))
    for amount in (99, 199, 4299, 100_099, 9_223_372_036_854_775_799):
        assert port.decide(request(amount, available)) == CENTS, (
            f"R42: {amount} (available {available}) was not refused as simulated_cents_rule"
        )


@pytest.mark.parametrize("amount", [0, 1, 98, 100, 4200, 4298, 4300, 9_223_372_036_854_775_800])
def test_r42_an_amount_not_ending_in_99_is_approved_at_rate_zero(amount: int) -> None:
    draws = Draws(0.0)  # the lowest draw: only a rate above zero could make it fire
    assert SimulatorCreditDecision(0.0, draws).decide(request(amount)) == Approve()


def test_r42_the_cents_rule_precedes_the_draw_and_the_draw_is_not_consumed() -> None:
    # the OTHER branch is at its certain-to-fire configuration: rate 1 and a source returning 0.
    # If the draw were evaluated first, a .99 amount would come back as simulated_failure_rate.
    draws = Draws(0.0)
    simulator = SimulatorCreditDecision(1.0, draws)

    assert simulator.decide(request(4299)) == CENTS, "R42: the draw won over the cents rule"
    assert draws.calls == 0, "R42: the failure-rate draw was consumed for a .99 amount"
    # the control row: the same simulator, an amount that does not end in 99, DOES draw and fire
    assert simulator.decide(request(4210)) == RATE
    assert draws.calls == 1


def test_r43_a_rate_of_one_refuses_every_amount_that_does_not_end_in_99() -> None:
    simulator = SimulatorCreditDecision(1.0, Draws(0.0))
    for amount in (0, 98, 100, 4210):
        assert simulator.decide(request(amount)) == RATE


def test_r43_the_comparison_is_strict_a_draw_equal_to_the_rate_approves() -> None:
    assert SimulatorCreditDecision(0.25, Draws(0.25)).decide(request(4210)) == Approve()
    assert SimulatorCreditDecision(0.25, Draws(0.2499999)).decide(request(4210)) == RATE
    assert SimulatorCreditDecision(0.25, Draws(0.2500001)).decide(request(4210)) == Approve()


@pytest.mark.parametrize("rate", [0.1, 0.3, 0.75])
def test_r43_the_configured_rate_is_measured_over_two_hundred_thousand_seeded_draws(
    rate: float,
) -> None:
    # #8's measured theory: the only guard that caught a rate applied at half strength. The source
    # is a seeded `random.Random`, so the count is the same on every run.
    draws = 200_000
    simulator = SimulatorCreditDecision(rate, random.Random(20261009).random)  # noqa: S311 - seeded test source, not security
    refused = sum(simulator.decide(request(25_000)) == RATE for _ in range(draws))
    observed = refused / draws  # a statistic about a test, not money
    assert abs(observed - rate) < 0.01, (
        f"R43: rate {rate} refused {observed:.4f} of {draws} seeded draws"
    )


def test_r43_the_default_random_source_never_disagrees_with_rates_zero_and_one() -> None:
    zero = SimulatorCreditDecision(0.0)
    one = SimulatorCreditDecision(1.0)
    for _ in range(2000):
        assert zero.decide(request(4210)) == Approve()
        assert one.decide(request(4210)) == RATE


@pytest.mark.parametrize("rate", [-0.0001, 1.0001, float("nan"), float("inf"), -float("inf")])
def test_r43_the_constructor_refuses_a_rate_outside_the_closed_unit_interval(rate: float) -> None:
    with pytest.raises(ValueError, match=r"closed interval \[0, 1\]"):
        SimulatorCreditDecision(rate)
    SimulatorCreditDecision(0.0)  # the control rows: both ends are inside
    SimulatorCreditDecision(1.0)


def test_the_simulator_is_synchronous_and_does_no_io() -> None:
    assert not inspect.iscoroutinefunction(SimulatorCreditDecision.decide)
    decision: CreditDecision = SimulatorCreditDecision(0.0, Draws(0.5)).decide(request(4210))
    assert decision == Approve()
