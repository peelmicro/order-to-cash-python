"""FS23 against a REAL `40P01` (I4, `design.md` 6.5): the victim is re-run and the reserve is
accepted once.

The construction: the test's own connection takes `FOR UPDATE` on P2; a reserve for `[P1, P2]` locks
P1 and waits on P2 (seen ungranted); the test's connection then asks `FOR UPDATE` on P1: a cycle.
The responder's backend waited first, so its `deadlock_timeout` expires first and it is the victim.
"""

import asyncio
import logging
import uuid
from typing import Any

COMPANY = "ACME-CO"
LOGGER = "otc_fulfillment.persistence.stock_transactions"
HEADERS = {
    "x-correlation-id": str(uuid.UUID(int=0xC0C0)),
    "x-request-id": str(uuid.UUID(int=0xCA05)),
}


async def test_fs23_a_real_40p01_on_a_reserve_is_rerun_and_the_reserve_is_accepted_once(
    fulfillment_host: Any, db: Any, rpc: Any, caplog: Any
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    await db.seed_stock(COMPANY, [("PRD-A1", 50, 0, 1), ("PRD-B2", 50, 0, 1)])
    hold = await db.hold([(COMPANY, "PRD-B2")])
    try:
        reserve = asyncio.create_task(
            rpc(
                "fulfillment.stock.reserve",
                {
                    "orderReference": "ORD-000042",
                    "retailerCode": "RET-9",
                    "companyCode": COMPANY,
                    "lines": [
                        {"productCode": "PRD-A1", "units": 2},
                        {"productCode": "PRD-B2", "units": 3},
                    ],
                },
                headers=HEADERS,
                timeout=30,
            )
        )
        # the reserve holds P1 and waits on P2 (ungranted), BEFORE the test closes the cycle
        await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 1)
        # the test's connection now asks for P1: held by the reserve, which waits on P2
        closing = asyncio.create_task(
            hold.fetch(
                "SELECT id FROM stock WHERE company_code = $1 AND product_code = $2 FOR UPDATE",
                COMPANY,
                "PRD-A1",
            )
        )
        # the responder is the victim (it waited first): the test's own statement is NOT an error
        rows = await asyncio.wait_for(closing, timeout=30)
        assert len(rows) == 1, "the test connection's own statement did not raise"
        await hold.rollback()  # releases P2 (and P1): attempt 2 proceeds

        reply = await asyncio.wait_for(reserve, timeout=30)
    finally:
        await hold.rollback()

    warnings = [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "40P01" in warnings[0].getMessage()
    assert reply["outcome"] == "accepted", reply
    [fact] = await db.outbox()
    assert fact["event_type"] == "stock.reserved.v1"
    assert len(await db.reservations("ORD-000042")) == 2
