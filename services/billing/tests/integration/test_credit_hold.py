"""`billing.credit.hold` through the real lifespan over real NATS and PostgreSQL (tasks H2 - H5).

R38 / R39 (the integration halves), BC1 (the fact's correlation and causation), BC3, BC4, BC7, BC8,
BC14 (a REFUSING port bound), BC28 (the five identity fields of every fact asserted against the
seeded line, not the request), BC38 (a zero hold).

Every fixture value is pairwise distinct and none contains another: the credit line id is random,
the order reference `ORD-000101`, the retailer `RETAIL-77`, the company `SUPPLY-CO`, the code
`CR-000321`, the correlation and request ids fresh UUIDs, and the amounts differ. Every
suppression asserts ZERO rows for ITS correlation id WITH a control row in the same test.

Loop scope: function. The host, its engine, its NATS client and the caller are created and closed
in the test's loop.
"""

import uuid
from typing import Any

from otc_billing.application.ports.credit_decision import (
    CreditDecision,
    CreditDecisionRequest,
    Refuse,
)
from otc_billing.domain.reasons import AdapterRejectionReason

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER = "ORD-000101"
OTHER_ORDER = "ORD-000202"
LIMIT = 100_000


def hold_body(
    order: str = ORDER,
    amount: int = 4210,
    *,
    currency: str = "EUR",
    retailer: str = RETAILER,
    company: str = COMPANY,
) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": retailer,
        "companyCode": company,
        "amount": {"amount": amount, "currency": currency},
    }


def ids() -> tuple[dict[str, str], str, str]:
    correlation, request = str(uuid.uuid4()), str(uuid.uuid4())
    return {"x-correlation-id": correlation, "x-request-id": request}, correlation, request


async def test_r38_an_approved_hold_appends_one_hold_row_and_emits_one_credit_approved_v1(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, correlation, request = ids()

    reply = await rpc("billing.credit.hold", hold_body(amount=4210), headers=headers)

    hold = decode.hold(reply)
    assert hold.outcome.value == "approved"
    assert (hold.held_amount, hold.available_credit, hold.reason) == (4210, LIMIT - 4210, None)
    assert (hold.order_reference, hold.credit_code, hold.currency) == (ORDER, CODE, "EUR")
    rows = await db.ledger_of(ORDER)
    assert len(rows) == 1, f"expected exactly one ledger row, got {len(rows)}"
    assert (rows[0]["type"], rows[0]["amount"], rows[0]["credit_id"]) == ("hold", 4210, line_id)
    facts = await db.outbox_rows_for(uuid.UUID(correlation))
    assert len(facts) == 1, f"expected exactly one fact for this correlation id, got {len(facts)}"
    fact = facts[0]
    assert fact["event_type"] == "credit.approved.v1"
    assert fact["aggregate_id"] == line_id
    assert fact["payload"] == {
        "orderReference": ORDER,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "creditCode": CODE,
        "currency": "EUR",
        "heldAmount": 4210,
        "availableCreditAfter": LIMIT - 4210,
    }, "a field of the credit.approved.v1 payload is not the seeded/supplied value"
    assert len(await db.outbox()) == 1, "exactly one fact in the whole outbox"
    assert str(fact["causation_id"]) == request


async def test_bc1_stamps_correlation_id_from_the_header_and_causation_id_from_the_request_id_on_the_credit_approved_fact(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, correlation, request = ids()
    assert correlation != request

    reply = await rpc("billing.credit.hold", hold_body(), headers=headers)

    assert decode.hold(reply).outcome.value == "approved"
    [fact] = await db.outbox()
    assert str(fact["correlation_id"]) == correlation, "correlationId is not x-correlation-id"
    assert str(fact["causation_id"]) == request, "causationId is not x-request-id"
    assert fact["correlation_id"] != fact["causation_id"]


async def test_r39_an_over_limit_hold_replies_rejected_appends_nothing_and_emits_one_credit_rejected_v1(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=10_000, code=CODE)
    await db.plant_entry(line_id, OTHER_ORDER, 3000, "hold")  # 7 000 left
    headers, correlation, request = ids()

    reply = await rpc("billing.credit.hold", hold_body(amount=7001), headers=headers)

    hold = decode.hold(reply)
    assert hold.outcome.value == "rejected"
    assert (hold.reason.value if hold.reason else None) == "over_limit"
    assert hold.held_amount is None
    assert hold.available_credit == 7000
    assert await db.count("credit_items") == 1, "zero new credit_items rows (the planted one stays)"
    assert await db.ledger_of(ORDER) == []
    facts = await db.outbox_rows_for(uuid.UUID(correlation))
    assert len(facts) == 1, f"expected exactly one fact for this correlation id, got {len(facts)}"
    fact = facts[0]
    assert fact["event_type"] == "credit.rejected.v1"
    assert fact["aggregate_id"] == line_id
    assert str(fact["causation_id"]) == request
    assert fact["payload"] == {
        "orderReference": ORDER,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "creditCode": CODE,
        "currency": "EUR",
        "requestedAmount": 7001,
        "availableCredit": 7000,
        "reason": "over_limit",
    }, "a field of the over-limit credit.rejected.v1 payload is wrong"
    # the control row: exactly 7 000 fits and is approved
    control_headers, control_correlation, _ = ids()
    control = await rpc(
        "billing.credit.hold",
        hold_body(order=OTHER_ORDER[:-1] + "3", amount=7000),
        headers=control_headers,
    )
    assert decode.hold(control).outcome.value == "approved"
    assert len(await db.outbox_rows_for(uuid.UUID(control_correlation))) == 1


async def test_bc3_replies_not_found_naming_the_pair_writing_no_ledger_entry_and_emitting_no_fact(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, correlation, _ = ids()

    reply = await rpc(
        "billing.credit.hold",
        hold_body(retailer="RETAIL-99", company="SUPPLY-99"),
        headers=headers,
    )

    error = decode.error(reply)
    assert error.code.value == "NOT_FOUND"
    assert error.details == {"retailerCode": "RETAIL-99", "companyCode": "SUPPLY-99"}
    assert await db.count("credit_items") == 0
    assert await db.outbox_rows_for(uuid.UUID(correlation)) == []
    # the control row: the seeded pair is found and does emit
    control_headers, control_correlation, _ = ids()
    ok = await rpc("billing.credit.hold", hold_body(), headers=control_headers)
    assert decode.hold(ok).outcome.value == "approved"
    assert len(await db.outbox_rows_for(uuid.UUID(control_correlation))) == 1


async def test_bc4_replies_validation_failed_writing_no_ledger_entry_and_emitting_no_fact_when_the_currency_differs(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, correlation, _ = ids()

    reply = await rpc("billing.credit.hold", hold_body(currency="USD"), headers=headers)

    error = decode.error(reply)
    assert error.code.value == "VALIDATION_FAILED"
    assert error.details == {"expected": "EUR", "received": "USD"}
    assert await db.count("credit_items") == 0
    assert await db.outbox_rows_for(uuid.UUID(correlation)) == []
    control_headers, control_correlation, _ = ids()
    ok = await rpc("billing.credit.hold", hold_body(currency="EUR"), headers=control_headers)
    assert decode.hold(ok).outcome.value == "approved"
    assert len(await db.outbox_rows_for(uuid.UUID(control_correlation))) == 1


class RefusingPort:
    def decide(self, request: CreditDecisionRequest) -> CreditDecision:
        return Refuse(AdapterRejectionReason.SIMULATED_FAILURE_RATE)


async def test_bc14_a_refusing_port_puts_one_credit_rejected_fact_with_its_reason_in_the_outbox(
    billing_host_factory: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, correlation, request = ids()
    async with billing_host_factory(credit_decision=RefusingPort()):
        reply = await rpc("billing.credit.hold", hold_body(amount=4210), headers=headers)

    hold = decode.hold(reply)
    assert hold.outcome.value == "rejected"
    assert (hold.reason.value if hold.reason else None) == "simulated_failure_rate"
    assert await db.count("credit_items") == 0, "a refusal appends nothing"
    facts = await db.outbox_rows_for(uuid.UUID(correlation))
    assert len(facts) == 1, f"expected exactly one fact for this correlation id, got {len(facts)}"
    fact = facts[0]
    assert fact["event_type"] == "credit.rejected.v1"
    assert fact["aggregate_id"] == line_id
    assert str(fact["causation_id"]) == request
    assert fact["payload"] == {
        "orderReference": ORDER,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "creditCode": CODE,
        "currency": "EUR",
        "requestedAmount": 4210,
        "availableCredit": LIMIT,
        "reason": "simulated_failure_rate",
    }, "a field of the port-refusal credit.rejected.v1 payload is wrong"


async def test_bc7_a_reissued_hold_answers_already_held_with_the_recorded_amount_and_the_current_credit_and_writes_nothing(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    first_headers, first_correlation, _ = ids()
    first = await rpc("billing.credit.hold", hold_body(amount=4210), headers=first_headers)
    assert decode.hold(first).outcome.value == "approved"
    # another order moves the CURRENT credit, so recorded and current differ
    other_headers, _, _ = ids()
    await rpc(
        "billing.credit.hold", hold_body(order=OTHER_ORDER, amount=1500), headers=other_headers
    )
    rows_before = await db.count("credit_items")
    facts_before = await db.count("outbox")

    again_headers, again_correlation, _ = ids()
    reply = await rpc("billing.credit.hold", hold_body(amount=999_00), headers=again_headers)

    hold = decode.hold(reply)
    assert hold.outcome.value == "already_held"
    assert hold.held_amount == 4210, "the RECORDED hold, not the re-issued amount"
    assert hold.available_credit == LIMIT - 4210 - 1500, "the CURRENT available credit"
    assert hold.reason is None
    assert await db.count("credit_items") == rows_before
    assert await db.count("outbox") == facts_before
    assert await db.outbox_rows_for(uuid.UUID(again_correlation)) == []
    assert len(await db.outbox_rows_for(uuid.UUID(first_correlation))) == 1, "the control row"


async def test_bc7_a_released_hold_reissued_still_answers_already_held(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, _, _ = ids()
    await rpc("billing.credit.hold", hold_body(amount=4210), headers=headers)
    release_headers, _, _ = ids()
    released = await rpc(
        "billing.credit.release",
        {"orderReference": ORDER, "retailerCode": RETAILER, "companyCode": COMPANY},
        headers=release_headers,
    )
    assert decode.release(released).released is True
    rows = await db.count("credit_items")

    again_headers, again_correlation, _ = ids()
    reply = await rpc("billing.credit.hold", hold_body(amount=4210), headers=again_headers)

    hold = decode.hold(reply)
    assert hold.outcome.value == "already_held", "a released hold must not re-approve (BC7)"
    assert hold.held_amount == 4210
    assert hold.available_credit == LIMIT
    assert await db.count("credit_items") == rows
    assert await db.outbox_rows_for(uuid.UUID(again_correlation)) == []


async def test_bc8_a_previously_rejected_hold_is_re_evaluated_and_writes_no_ledger_entry_either_time(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=1000, code=CODE)
    first_headers, first_correlation, _ = ids()
    first = await rpc("billing.credit.hold", hold_body(amount=4210), headers=first_headers)
    assert decode.hold(first).outcome.value == "rejected"
    assert await db.count("credit_items") == 0

    second_headers, second_correlation, _ = ids()
    second = await rpc("billing.credit.hold", hold_body(amount=4210), headers=second_headers)
    assert decode.hold(second).outcome.value == "rejected", "re-evaluated, not already_held"
    assert await db.count("credit_items") == 0
    [fact_one] = await db.outbox_rows_for(uuid.UUID(first_correlation))
    [fact_two] = await db.outbox_rows_for(uuid.UUID(second_correlation))
    assert fact_one["event_id"] != fact_two["event_id"], "a second fact with a distinct eventId"

    # the limit is raised: the same request is now approved (the control row)
    await db.execute("UPDATE credits SET credit_limit = 100000 WHERE id = $1", line_id)
    third_headers, _, _ = ids()
    third = await rpc("billing.credit.hold", hold_body(amount=4210), headers=third_headers)
    assert decode.hold(third).outcome.value == "approved"
    assert await db.count("credit_items") == 1


async def test_bc38_a_zero_amount_hold_is_approved(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    headers, correlation, _ = ids()

    reply = await rpc("billing.credit.hold", hold_body(amount=0), headers=headers)

    hold = decode.hold(reply)
    assert hold.outcome.value == "approved"
    assert hold.held_amount == 0, "heldAmount: 0 must be written, not omitted"
    assert hold.available_credit == LIMIT
    [row] = await db.ledger_of(ORDER)
    assert (row["type"], row["amount"]) == ("hold", 0)
    facts = await db.outbox_rows_for(uuid.UUID(correlation))
    assert len(facts) == 1, f"expected exactly one fact for this correlation id, got {len(facts)}"
    fact = facts[0]
    assert fact["event_type"] == "credit.approved.v1"
    assert fact["payload"]["heldAmount"] == 0
    assert fact["payload"]["availableCreditAfter"] == LIMIT
