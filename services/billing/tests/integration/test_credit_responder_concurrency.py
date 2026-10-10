"""BC21 against a held row lock, and the release's wait on the line lock (tasks I3, I4).

The test holds line A `FOR UPDATE`; a request that waits on it must not delay an unrelated request
on line B (the responder serves each request in its own task), and a release takes the SAME line
lock as a hold.

Loop scope: function. The host, the caller and the lock-holding connection are created and closed
in the test's loop.
"""

import asyncio
import uuid
from typing import Any

import pytest


def hold_body(retailer: str, company: str, order: str, amount: int) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": retailer,
        "companyCode": company,
        "amount": {"amount": amount, "currency": "EUR"},
    }


def headers() -> dict[str, str]:
    return {"x-correlation-id": str(uuid.uuid4()), "x-request-id": str(uuid.uuid4())}


async def test_bc21_answers_a_second_request_while_an_earlier_one_waits_on_a_credit_row_lock(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await db.seed_line("RETAIL-A1", "SUPPLY-CO", limit=100_000, code="CR-000411")
    await db.seed_line("RETAIL-B2", "SUPPLY-CO", limit=100_000, code="CR-000422")
    hold = await db.hold("RETAIL-A1", "SUPPLY-CO")
    pending: asyncio.Task[dict[str, Any]] | None = None
    try:
        pending = asyncio.create_task(
            rpc(
                "billing.credit.hold",
                hold_body("RETAIL-A1", "SUPPLY-CO", "ORD-000101", 4210),
                headers=headers(),
            )
        )
        await db.wait_for_lock_waiters("%", 1)  # the hold for A is seen waiting on the line

        try:
            async with asyncio.timeout(10):
                b_reply = await rpc(
                    "billing.credit.hold",
                    hold_body("RETAIL-B2", "SUPPLY-CO", "ORD-000202", 1230),
                    headers=headers(),
                )
        except TimeoutError:
            pytest.fail("BC21: a request on line B was not answered while line A's request waited")
        assert decode.hold(b_reply).outcome.value == "approved"
        assert not pending.done(), "the request on the held line must still be waiting"
    finally:
        await hold.commit()
    a_reply = await pending
    assert decode.hold(a_reply).outcome.value == "approved"
    assert await db.count("credit_items") == 2


async def test_the_release_waits_on_the_line_lock(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    line_id = await db.seed_line("RETAIL-77", "SUPPLY-CO", limit=100_000, code="CR-000321")
    await db.plant_entry(line_id, "ORD-000101", 4210, "hold")
    hold = await db.hold("RETAIL-77", "SUPPLY-CO")
    try:
        release = asyncio.create_task(
            rpc(
                "billing.credit.release",
                {
                    "orderReference": "ORD-000101",
                    "retailerCode": "RETAIL-77",
                    "companyCode": "SUPPLY-CO",
                },
                headers=headers(),
            )
        )
        # seen waiting on the LINE lock itself (the credits row select), not merely at its insert:
        # an unlocked release would still block there on the foreign key's key-share lock (measured)
        await db.wait_for_lock_waiters("%FROM credits%FOR UPDATE%", 1)
        assert not release.done()
        assert await db.count("credit_items") == 1, "nothing was written while the lock was held"
    finally:
        await hold.commit()
    released = decode.release(await release)
    assert released.released is True
    assert released.released_amount == 4210
    assert await db.count("credit_items") == 2
