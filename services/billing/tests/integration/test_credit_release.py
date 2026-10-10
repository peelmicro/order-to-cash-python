"""`billing.credit.release` through the real lifespan (tasks H5; BC25, BC3, BC28).

Loop scope: function. The host and the caller are created and closed in the test's loop.
"""

import uuid
from typing import Any

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER = "ORD-000101"
LIMIT = 100_000
# Another order's active hold on the same line (D1): available-after (70 000) is neither the
# limit (100 000) nor the value before the release (65 790).
OTHER = "ORD-000202"
OTHER_HOLD = 30_000
AFTER = LIMIT - OTHER_HOLD


def release_body(
    order: str = ORDER, *, retailer: str = RETAILER, company: str = COMPANY
) -> dict[str, Any]:
    return {"orderReference": order, "retailerCode": retailer, "companyCode": company}


def ids() -> tuple[dict[str, str], str, str]:
    correlation, request = str(uuid.uuid4()), str(uuid.uuid4())
    return {"x-correlation-id": correlation, "x-request-id": request}, correlation, request


async def test_bc25_one_release_entry_and_one_released_fact_then_released_false_writing_nothing_on_a_repeat(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    await db.plant_entry(line_id, ORDER, 4210, "hold")
    await db.plant_entry(line_id, OTHER, OTHER_HOLD, "hold")
    headers, correlation, request = ids()

    reply = await rpc("billing.credit.release", release_body(), headers=headers)

    released = decode.release(reply)
    assert released.released is True
    assert (released.released_amount, released.available_credit_after) == (4210, AFTER)
    assert (released.order_reference, released.credit_code, released.currency) == (
        ORDER,
        CODE,
        "EUR",
    )
    rows = await db.ledger_of(ORDER)
    assert [(r["type"], r["amount"]) for r in rows] == [("hold", 4210), ("release", 4210)]
    [fact] = await db.outbox_rows_for(uuid.UUID(correlation))
    assert fact["event_type"] == "credit.released.v1"
    assert fact["aggregate_id"] == line_id
    assert str(fact["causation_id"]) == request
    assert fact["payload"] == {
        "orderReference": ORDER,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "creditCode": CODE,
        "currency": "EUR",
        "releasedAmount": 4210,
        "availableCreditAfter": AFTER,
        "reason": "order_cancelled",
    }, "a field of the credit.released.v1 payload is wrong"

    # the repeat: success, not an error; nothing written, no second fact
    again_headers, again_correlation, _ = ids()
    again = await rpc("billing.credit.release", release_body(), headers=again_headers)
    repeat = decode.release(again)
    assert repeat.released is False
    assert repeat.released_amount is None
    assert repeat.available_credit_after == AFTER
    assert len(await db.ledger_of(ORDER)) == 2, "the repeat wrote a ledger row"
    assert await db.outbox_rows_for(uuid.UUID(again_correlation)) == []
    assert len(await db.outbox()) == 1, "the repeat emitted a fact"
    assert "releasedAmount" not in again


async def test_bc3_release_replies_not_found_for_an_unknown_pair(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    await db.plant_entry(line_id, ORDER, 4210, "hold")
    headers, correlation, _ = ids()

    reply = await rpc(
        "billing.credit.release",
        release_body(retailer="RETAIL-99", company="SUPPLY-99"),
        headers=headers,
    )

    error = decode.error(reply)
    assert error.code.value == "NOT_FOUND"
    assert error.details == {"retailerCode": "RETAIL-99", "companyCode": "SUPPLY-99"}
    assert await db.count("credit_items") == 1, "only the planted hold"
    assert await db.outbox_rows_for(uuid.UUID(correlation)) == []
    # the control row: the seeded pair releases and does emit
    control_headers, control_correlation, _ = ids()
    ok = await rpc("billing.credit.release", release_body(), headers=control_headers)
    assert decode.release(ok).released is True
    assert len(await db.outbox_rows_for(uuid.UUID(control_correlation))) == 1


async def test_a_release_of_an_order_that_was_never_held_is_released_false(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    await db.plant_entry(line_id, OTHER, OTHER_HOLD, "hold")
    headers, correlation, _ = ids()
    reply = await rpc("billing.credit.release", release_body(), headers=headers)
    released = decode.release(reply)
    assert released.released is False
    assert released.available_credit_after == AFTER
    assert await db.count("credit_items") == 1, "only the other order's planted hold"
    assert await db.outbox_rows_for(uuid.UUID(correlation)) == []
