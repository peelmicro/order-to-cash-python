"""The constructed races of `billing.credit.hold` (tasks I1, I2; BC9, BC35, B4).

A change of KIND, not of probability: the test's own connection holds `FOR UPDATE` on the credit
line; both holds are sent; the test waits until TWO lock requests are seen ungranted
(`pg_stat_activity`), and only then commits. Correct code serialises the two transactions on the
line row; the second reads the first's committed entry in a fresh `READ COMMITTED` statement.

Loop scope: function. The host, the caller and the lock-holding connection are created and closed
in the test's loop.
"""

import asyncio
import uuid
from typing import Any

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER_A = "ORD-000101"
ORDER_B = "ORD-000202"


def hold_body(order: str, amount: int) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "amount": {"amount": amount, "currency": "EUR"},
    }


def headers() -> tuple[dict[str, str], str]:
    correlation = str(uuid.uuid4())
    return {"x-correlation-id": correlation, "x-request-id": str(uuid.uuid4())}, correlation


async def test_bc9_two_concurrent_holds_against_one_nearly_exhausted_line_yield_one_approval_and_one_rejection(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=10_000, code=CODE)  # room for exactly one 6 000
    hold = await db.hold(RETAILER, COMPANY)
    try:
        headers_a, correlation_a = headers()
        headers_b, correlation_b = headers()
        first = asyncio.create_task(
            rpc("billing.credit.hold", hold_body(ORDER_A, 6000), headers=headers_a)
        )
        second = asyncio.create_task(
            rpc("billing.credit.hold", hold_body(ORDER_B, 6000), headers=headers_b)
        )
        await db.wait_for_lock_waiters("%", 2)
    finally:
        await hold.commit()
    replies = await asyncio.gather(first, second)

    outcomes = sorted(decode.hold(reply).outcome.value for reply in replies)
    assert outcomes == ["approved", "rejected"], (
        f"BC9: two holds for 6 000 against 10 000 of credit answered {outcomes}"
    )
    rejected = next(decode.hold(r) for r in replies if r["outcome"] == "rejected")
    assert rejected.reason is not None
    assert rejected.reason.value == "over_limit"
    [row] = await db.fetch(
        "SELECT COALESCE(SUM(CASE type WHEN 'hold' THEN amount WHEN 'release' THEN -amount"
        " ELSE 0 END), 0)::bigint AS committed FROM credit_items"
    )
    assert row["committed"] == 6000 <= 10_000, "the committed exposure exceeds the credit limit"
    facts = await db.outbox()
    assert sorted(f["event_type"] for f in facts) == ["credit.approved.v1", "credit.rejected.v1"]
    assert {str(f["correlation_id"]) for f in facts} == {correlation_a, correlation_b}


async def test_b4_two_concurrent_holds_for_one_order_yield_one_approval_and_one_already_held(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=10_000, code=CODE)  # room for both
    hold = await db.hold(RETAILER, COMPANY)
    try:
        headers_a, _ = headers()
        headers_b, _ = headers()
        first = asyncio.create_task(
            rpc("billing.credit.hold", hold_body(ORDER_A, 3000), headers=headers_a)
        )
        second = asyncio.create_task(
            rpc("billing.credit.hold", hold_body(ORDER_A, 3000), headers=headers_b)
        )
        await db.wait_for_lock_waiters("%", 2)
    finally:
        await hold.commit()
    replies = await asyncio.gather(first, second)

    outcomes = sorted(decode.hold(reply).outcome.value for reply in replies)
    assert outcomes == ["already_held", "approved"], (
        f"B4: two holds for ONE order answered {outcomes}"
    )
    rows = await db.ledger_of(ORDER_A)
    assert len(rows) == 1, f"B4: {len(rows)} hold rows for one order"
    assert [f["event_type"] for f in await db.outbox()] == ["credit.approved.v1"]
