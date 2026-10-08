"""FS18 (H9): a second request is ANSWERED while an earlier one is blocked on a stock row lock held
by another transaction (`design.md` 13.3). The held-lock construction: nothing here sleeps to wait
for a state; the lock wait is observed ungranted in `pg_stat_activity`."""

import asyncio
import uuid
from typing import Any

COMPANY = "ACME-CO"


def headers(n: int) -> dict[str, str]:
    return {
        "x-correlation-id": str(uuid.UUID(int=0xC000 + n)),
        "x-request-id": str(uuid.UUID(int=0xCA00 + n)),
    }


def reserve_body(order: str, product: str) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": "RET-9",
        "companyCode": COMPANY,
        "lines": [{"productCode": product, "units": 1}],
    }


async def test_fs18_answers_a_second_request_while_an_earlier_one_is_blocked_on_a_stock_row_lock_held_by_another_transaction(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3), ("PRD-B2", 10, 0, 3)])
    hold = await db.hold([(COMPANY, "PRD-A1")])
    try:
        first = asyncio.create_task(
            rpc(
                "fulfillment.stock.reserve",
                reserve_body("ORD-000042", "PRD-A1"),
                headers=headers(1),
            )
        )
        await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 1)
        assert not first.done()

        # a request on ANOTHER row, and one on another subject, are answered meanwhile
        second = await asyncio.wait_for(
            rpc(
                "fulfillment.stock.reserve",
                reserve_body("ORD-000043", "PRD-B2"),
                headers=headers(2),
            ),
            timeout=10,
        )
        listed = await asyncio.wait_for(rpc("fulfillment.stock.list", {}), timeout=10)

        assert second["outcome"] == "accepted"
        assert len(listed["items"]) == 2
        assert not first.done(), "the first request is still waiting on the lock"

        await hold.commit()
        assert (await asyncio.wait_for(first, timeout=15))["outcome"] == "accepted"
    finally:
        await hold.rollback()
