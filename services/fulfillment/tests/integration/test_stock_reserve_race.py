"""The constructed races of `fulfillment.stock.reserve` (I1 - I3, `design.md` 13.3): a change of
KIND, not of probability. The test holds `FOR UPDATE` on the stock rows, sends the requests, waits
until the lock waits are seen UNGRANTED in `pg_stat_activity`, then releases them: each outcome is
decided by the locks, not by timing.
"""

import asyncio
import logging
import uuid
from typing import Any

import pytest

COMPANY = "ACME-CO"
DEADLOCK_LOGGER = "otc_fulfillment.persistence.stock_transactions"


def headers(n: int) -> dict[str, str]:
    return {
        "x-correlation-id": str(uuid.UUID(int=0xC000 + n)),
        "x-request-id": str(uuid.UUID(int=0xCA00 + n)),
    }


def reserve_body(order: str, *lines: tuple[str, int]) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": "RET-9",
        "companyCode": COMPANY,
        "lines": [{"productCode": code, "units": units} for code, units in lines],
    }


async def test_fs6_two_concurrent_reserves_for_the_last_units_yield_exactly_one_stock_reserved_and_one_stock_rejected(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 5, 0, 1)])  # room for ONE order of 4
    hold = await db.hold([(COMPANY, "PRD-A1")])
    try:
        first = asyncio.create_task(
            rpc(
                "fulfillment.stock.reserve",
                reserve_body("ORD-000041", ("PRD-A1", 4)),
                headers=headers(1),
            )
        )
        second = asyncio.create_task(
            rpc(
                "fulfillment.stock.reserve",
                reserve_body("ORD-000042", ("PRD-A1", 4)),
                headers=headers(2),
            )
        )
        # both requests are waiting on a lock; neither has decided anything yet
        await db.wait_for_lock_waiters("%", 2)
        assert not first.done()
        assert not second.done()
        await hold.commit()
        replies = {1: await asyncio.wait_for(first, 20), 2: await asyncio.wait_for(second, 20)}
    finally:
        await hold.rollback()

    outcomes = sorted(r["outcome"] for r in replies.values())
    assert outcomes == ["accepted", "rejected"], f"exactly one wins the last units: {replies}"
    winner = next(n for n, r in replies.items() if r["outcome"] == "accepted")
    loser = 3 - winner
    assert (await db.stock(COMPANY, "PRD-A1"))["reserved_units"] == 4
    outbox = await db.outbox()
    by_type = {row["event_type"]: row for row in outbox}
    assert sorted(by_type) == ["stock.rejected.v1", "stock.reserved.v1"], "one of each, no more"
    assert len(outbox) == 2
    assert (
        str(by_type["stock.reserved.v1"]["correlation_id"]) == headers(winner)["x-correlation-id"]
    )
    assert str(by_type["stock.rejected.v1"]["correlation_id"]) == headers(loser)["x-correlation-id"]
    assert by_type["stock.rejected.v1"]["payload"]["shortages"] == [
        {"productCode": "PRD-A1", "requested": 4, "available": 1}
    ], "the loser read the counter the winner committed"


async def test_fs7_a_line_reported_sufficient_by_stock_check_is_rejected_by_a_later_reserve_once_another_order_took_the_units(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 5, 0, 1)])

    check = await rpc(
        "fulfillment.stock.check",
        {"companyCode": COMPANY, "lines": [{"productCode": "PRD-A1", "quantity": 3}]},
    )
    assert check["lines"][0]["sufficient"] is True
    # the check held nothing: another order takes 4 of the 5 units
    taken = await rpc(
        "fulfillment.stock.reserve", reserve_body("ORD-000041", ("PRD-A1", 4)), headers=headers(1)
    )
    assert taken["outcome"] == "accepted"

    later = await rpc(
        "fulfillment.stock.reserve", reserve_body("ORD-000042", ("PRD-A1", 3)), headers=headers(2)
    )

    assert later["outcome"] == "rejected"
    assert later["shortages"] == [{"productCode": "PRD-A1", "requested": 3, "available": 1}]


async def test_fs19_two_multi_line_reserves_naming_the_same_products_in_opposite_order_both_succeed_with_no_deadlock(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=DEADLOCK_LOGGER)
    await db.seed_stock(COMPANY, [("PRD-A1", 50, 0, 1), ("PRD-B2", 50, 0, 1)])
    hold = await db.hold([(COMPANY, "PRD-A1"), (COMPANY, "PRD-B2")])
    try:
        forward = asyncio.create_task(
            rpc(
                "fulfillment.stock.reserve",
                reserve_body("ORD-000041", ("PRD-A1", 1), ("PRD-B2", 1)),
                headers=headers(1),
            )
        )
        backward = asyncio.create_task(
            rpc(
                "fulfillment.stock.reserve",
                reserve_body("ORD-000042", ("PRD-B2", 1), ("PRD-A1", 1)),
                headers=headers(2),
            )
        )
        await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 2)
        await hold.commit()
        replies = [await asyncio.wait_for(forward, 30), await asyncio.wait_for(backward, 30)]
    finally:
        await hold.rollback()

    assert [r["outcome"] for r in replies] == ["accepted", "accepted"]
    deadlocks = [r for r in caplog.records if r.name == DEADLOCK_LOGGER]
    assert deadlocks == [], (
        f"no transaction was a deadlock victim: {[r.getMessage() for r in deadlocks]}"
    )
    assert len(await db.outbox()) == 2
