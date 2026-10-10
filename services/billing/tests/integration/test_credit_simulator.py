"""The credit-check simulator bound by the REAL composition root (feature 20; R42 - R44 over the
real wire: NATS request / reply, PostgreSQL, the outbox `payload` column).

Every host here is `otc_billing.main.create_app()`'s lifespan with no injected adapter: the
simulator is the default binding and `CREDIT_FAILURE_RATE` is read from the process environment.
Fixture values are pairwise distinct and none contains another: the line is `CR-000321`
(`RETAIL-77` / `SUPPLY-CO`, limit 100 000), the orders `ORD-000101` ... `ORD-000404`.

Loop scope: function. The host, its engine and its NATS client live in the test's loop.
"""

import uuid
from typing import Any

import nats
import pytest
from pydantic import ValidationError

import otc_billing.composition as composition
from otc_billing.infrastructure.credit.simulator import SimulatorCreditDecision

from .test_credit_hold import CODE, COMPANY, LIMIT, ORDER, RETAILER, hold_body, ids

CENTS_AMOUNT = 4299  # ends in 99
PLAIN_AMOUNT = 4210
OVER_LIMIT_AMOUNT = LIMIT + 1
OTHER_ORDER = "ORD-000202"
THIRD_ORDER = "ORD-000303"
FOURTH_ORDER = "ORD-000404"


async def test_r42_a_total_ending_in_99_is_refused_with_the_cents_rule_over_the_wire(
    billing_host_factory: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, correlation, request = ids()
    async with billing_host_factory():
        reply = await rpc(
            "billing.credit.hold",
            hold_body(amount=CENTS_AMOUNT),
            headers=headers,
            allow_cents_rule=True,
        )
        control_headers, control_correlation, _ = ids()
        control = await rpc(
            "billing.credit.hold",
            hold_body(order=OTHER_ORDER, amount=PLAIN_AMOUNT),
            headers=control_headers,
        )

    hold = decode.hold(reply)
    assert hold.outcome.value == "rejected"
    assert (hold.reason.value if hold.reason else None) == "simulated_cents_rule"
    assert hold.available_credit == LIMIT, "ample credit: the rule fires regardless of it"
    assert await db.ledger_of(ORDER) == [], "R42: no ledger entry is appended"
    [fact] = await db.outbox_rows_for(uuid.UUID(correlation))
    assert fact["event_type"] == "credit.rejected.v1"
    assert fact["aggregate_id"] == line_id
    assert str(fact["causation_id"]) == request
    assert fact["payload"] == {
        "orderReference": ORDER,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "creditCode": CODE,
        "currency": "EUR",
        "requestedAmount": CENTS_AMOUNT,
        "availableCredit": LIMIT,
        "reason": "simulated_cents_rule",
    }, "a field of the simulated credit.rejected.v1 payload is wrong"
    # the control row: a plain amount on the same host, same line, is approved
    assert decode.hold(control).outcome.value == "approved"
    assert len(await db.outbox_rows_for(uuid.UUID(control_correlation))) == 1


async def test_r43_the_failure_rate_defaults_to_zero_so_a_fitting_plain_hold_is_approved(
    billing_host_factory: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    # an EMPTY variable is "not supplied" (absent is proven by the unit settings test): rate 0
    async with billing_host_factory(CREDIT_FAILURE_RATE="") as host:
        assert host.runtime.settings.credit_simulator.failure_rate == 0
        for index, order in enumerate((ORDER, OTHER_ORDER, THIRD_ORDER, FOURTH_ORDER)):
            reply = await rpc(
                "billing.credit.hold", hold_body(order=order, amount=100 + index), headers=ids()[0]
            )
            assert decode.hold(reply).outcome.value == "approved", f"rate 0 refused {order}"
    assert await db.count("credit_items") == 4


async def test_r43_a_rate_of_one_in_the_environment_refuses_a_plain_hold_and_the_ordering_holds(
    billing_host_factory: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    plain_headers, plain_correlation, _ = ids()
    cents_headers, cents_correlation, _ = ids()
    async with billing_host_factory(CREDIT_FAILURE_RATE="1"):
        plain = await rpc(
            "billing.credit.hold", hold_body(amount=PLAIN_AMOUNT), headers=plain_headers
        )
        cents = await rpc(
            "billing.credit.hold",
            hold_body(order=OTHER_ORDER, amount=CENTS_AMOUNT),
            headers=cents_headers,
            allow_cents_rule=True,
        )

    assert (decode.hold(plain).reason or None) is not None
    assert decode.hold(plain).reason.value == "simulated_failure_rate"
    [plain_fact] = await db.outbox_rows_for(uuid.UUID(plain_correlation))
    assert plain_fact["aggregate_id"] == line_id
    assert plain_fact["payload"]["reason"] == "simulated_failure_rate"
    # the ordering, at the wire: rate 1 would refuse everything, yet the .99 amount says cents rule
    assert decode.hold(cents).reason.value == "simulated_cents_rule"
    [cents_fact] = await db.outbox_rows_for(uuid.UUID(cents_correlation))
    assert cents_fact["payload"]["reason"] == "simulated_cents_rule"
    assert await db.count("credit_items") == 0, "a simulated refusal appends nothing"


async def test_r43_the_rate_the_environment_carries_reaches_the_simulator_the_root_builds(
    billing_host_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[float] = []

    class Recording(SimulatorCreditDecision):
        def __init__(self, failure_rate: float, *args: Any, **kwargs: Any) -> None:
            built.append(failure_rate)
            super().__init__(failure_rate, *args, **kwargs)

    monkeypatch.setattr(composition, "SimulatorCreditDecision", Recording)

    async with billing_host_factory(CREDIT_FAILURE_RATE="0.37"):
        pass

    assert built == [0.37], "CREDIT_FAILURE_RATE must reach the simulator the root builds, once"


@pytest.mark.parametrize("raw", ["1.5", "-0.1", "nan", "inf", "abc", "1_0", "0x1"])
async def test_r43_a_bad_rate_refuses_to_boot_naming_the_value_before_connecting(
    billing_host_factory: Any, raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def connected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail(f"R43: the boot reached NATS with CREDIT_FAILURE_RATE={raw!r}: not refused")

    # the boot that does not refuse fails here, within seconds, naming R43 and the value
    monkeypatch.setattr(nats, "connect", connected)
    # the database, NATS and Kafka addresses are dead too: the refusal must come from the
    # settings, through the real lifespan, before anything is opened
    with pytest.raises(ValidationError) as refused:
        async with billing_host_factory(
            CREDIT_FAILURE_RATE=raw,
            BILLING_DATABASE_URL="postgresql+asyncpg://nobody:x@127.0.0.1:1/none",
            NATS_URL="nats://127.0.0.1:1",
        ):
            pytest.fail(f"CREDIT_FAILURE_RATE={raw!r} must not boot")

    message = " ".join(str(e["msg"]) for e in refused.value.errors())  # the validator's own text
    assert "CREDIT_FAILURE_RATE" in message
    assert repr(raw) in message, "the failure does not report the offending value"


async def test_r44_a_simulated_and_a_genuine_rejection_share_fact_type_and_payload_keys(
    billing_host_factory: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    sim_headers, sim_correlation, _ = ids()
    gen_headers, gen_correlation, _ = ids()
    # rate 0: the over-limit rejection stays reachable with the simulator bound (R37 not bypassed)
    async with billing_host_factory(CREDIT_FAILURE_RATE="0"):
        simulated = await rpc(
            "billing.credit.hold",
            hold_body(order=ORDER, amount=CENTS_AMOUNT),
            headers=sim_headers,
            allow_cents_rule=True,
        )
        genuine = await rpc(
            "billing.credit.hold",
            hold_body(order=OTHER_ORDER, amount=OVER_LIMIT_AMOUNT),
            headers=gen_headers,
        )

    assert decode.hold(simulated).reason.value == "simulated_cents_rule"
    assert decode.hold(genuine).reason.value == "over_limit"
    [sim_fact] = await db.outbox_rows_for(uuid.UUID(sim_correlation))
    [gen_fact] = await db.outbox_rows_for(uuid.UUID(gen_correlation))
    # compared to EACH OTHER, never to a hand-typed key list
    assert sim_fact["event_type"] == gen_fact["event_type"] == "credit.rejected.v1"
    assert sorted(sim_fact["payload"]) == sorted(gen_fact["payload"]), (
        "R44: the two credit.rejected.v1 payloads have different key sets"
    )
    assert sorted(simulated) == sorted(genuine), "R44: the two RPC replies have different key sets"
    differing_fact = {
        k for k in sim_fact["payload"] if sim_fact["payload"][k] != gen_fact["payload"][k]
    }
    assert differing_fact == {"orderReference", "requestedAmount", "reason"}
    differing_reply = {k for k in simulated if simulated[k] != genuine[k]}
    assert "reason" in differing_reply
    assert await db.count("credit_items") == 0


async def test_the_fixture_guard_still_refuses_a_99_amount_with_the_simulator_bound(
    billing_host_factory: Any, db: Any, rpc: Any
) -> None:
    # #7 N2 / #8 N2: the guard sits in the `rpc` fixture every test calls; with the simulator the
    # default binding, an unflagged .99 fixture would silently change meaning, so it must raise
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    async with billing_host_factory():
        with pytest.raises(AssertionError, match="ends in 99"):
            await rpc("billing.credit.hold", hold_body(amount=CENTS_AMOUNT), headers=ids()[0])
    assert await db.count("outbox") == 0, "the refused fixture must not have reached the host"
