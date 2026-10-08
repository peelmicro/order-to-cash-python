"""R31, FS22 and R31's "non-locking" (H1, H2): `fulfillment.stock.check` through the real host."""

import asyncio
import uuid
from typing import Any

import asyncpg

COMPANY = "ACME-CO"
HEADERS = {"x-correlation-id": str(uuid.UUID(int=0xC0)), "x-request-id": str(uuid.UUID(int=0xCA))}


async def test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 4, 3), ("PRD-B2", 3, 0, 1), ("PRD-C3", 50, 0, 1)])
    before = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]

    reply = await rpc(
        "fulfillment.stock.check",
        {
            "companyCode": COMPANY,
            "lines": [
                {"productCode": "PRD-A1", "quantity": 6},  # available 6: sufficient, exactly
                {"productCode": "PRD-B2", "quantity": 5},  # available 3: short
            ],
        },
    )

    assert reply == {
        "available": False,
        "lines": [
            {"productCode": "PRD-A1", "requested": 6, "available": 6, "sufficient": True},
            {"productCode": "PRD-B2", "requested": 5, "available": 3, "sufficient": False},
        ],
    }
    after = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]
    assert after == before, "a check mutates no stock item"
    assert await db.outbox() == [], "a check emits no fact"
    assert await db.fetch("SELECT 1 FROM reservations") == []

    # control row: a reserve in the same test DOES emit, so the outbox read can see a row
    reserved = await rpc(
        "fulfillment.stock.reserve",
        {
            "orderReference": "ORD-000042",
            "retailerCode": "RET-9",
            "companyCode": COMPANY,
            "lines": [{"productCode": "PRD-C3", "units": 2}],
        },
        headers=HEADERS,
    )
    assert reserved["outcome"] == "accepted"
    [row] = await db.outbox()
    assert row["event_type"] == "stock.reserved.v1"

    # and a second check, after the control, still adds nothing
    await rpc(
        "fulfillment.stock.check",
        {"companyCode": COMPANY, "lines": [{"productCode": "PRD-A1", "quantity": 1}]},
    )
    assert len(await db.outbox()) == 1


async def test_fs22_answers_an_unknown_product_with_available_zero_and_sufficient_false_never_with_an_rpc_error(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])

    reply = await rpc(
        "fulfillment.stock.check",
        {
            "companyCode": COMPANY,
            "lines": [
                {"productCode": "PRD-Z9", "quantity": 2},
                {"productCode": "PRD-A1", "quantity": 1},
            ],
        },
    )

    assert "code" not in reply, f"an unknown product is not an RpcError: {reply}"
    assert reply == {
        "available": False,
        "lines": [
            {"productCode": "PRD-Z9", "requested": 2, "available": 0, "sufficient": False},
            {"productCode": "PRD-A1", "requested": 1, "available": 10, "sufficient": True},
        ],
    }
    # a company the item does not belong to is unknown too
    other = await rpc(
        "fulfillment.stock.check",
        {"companyCode": "OTHER-CO", "lines": [{"productCode": "PRD-A1", "quantity": 1}]},
    )
    assert other["lines"][0]["available"] == 0


async def test_a_check_is_answered_while_a_test_transaction_holds_the_row_for_update(
    fulfillment_host: Any, db: Any, rpc: Any, migrated_db: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 4, 3)])
    holder = await asyncpg.connect(migrated_db.dsn)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.fetch(
            "SELECT * FROM stock WHERE company_code = $1 AND product_code = $2 FOR UPDATE",
            COMPANY,
            "PRD-A1",
        )

        reply = await asyncio.wait_for(
            rpc(
                "fulfillment.stock.check",
                {"companyCode": COMPANY, "lines": [{"productCode": "PRD-A1", "quantity": 6}]},
            ),
            timeout=10,
        )

        assert reply["lines"][0]["available"] == 6, (
            "answered from the committed row, lock or no lock"
        )
        await transaction.rollback()
    finally:
        await holder.close()
