"""`fulfillment.stock.release` through the real host: the release itself (#8 D2: the released
fact's `reason` and every field are opened), R34's idempotency, FS9, FS10 and FS25's lock (H7, I5).
"""

import asyncio
import uuid
from typing import Any

import pytest

COMPANY = "ACME-CO"
RETAILER = "RET-9"
ORDER = "ORD-000042"
RESERVE_HEADERS = {
    "x-correlation-id": str(uuid.UUID(int=0xC0C0)),
    "x-request-id": str(uuid.UUID(int=0xCA05)),
}
RELEASE_CORRELATION = str(uuid.UUID(int=0xD0D0))
RELEASE_REQUEST = str(uuid.UUID(int=0xDA05))
RELEASE_HEADERS = {"x-correlation-id": RELEASE_CORRELATION, "x-request-id": RELEASE_REQUEST}


def reserve_body(*lines: tuple[str, int], order: str = ORDER) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "lines": [{"productCode": code, "units": units} for code, units in lines],
    }


def release_body(order: str = ORDER, reason: str = "order_cancelled") -> dict[str, Any]:
    return {"orderReference": order, "reason": reason}


async def reserved_order(db: Any, rpc: Any) -> tuple[dict[str, uuid.UUID], dict[str, Any]]:
    ids: dict[str, uuid.UUID] = await db.seed_stock(
        COMPANY, [("PRD-A1", 10, 1, 3), ("PRD-B2", 20, 2, 3)]
    )
    first = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 3), ("PRD-B2", 5)),
        headers=RESERVE_HEADERS,
    )
    assert first["outcome"] == "accepted"
    return ids, first


def facts_of(outbox: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [row for row in outbox if row["event_type"] == event_type]


async def test_the_release_releases_every_reservation_lowers_the_counters_and_writes_exactly_one_released_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    ids, first = await reserved_order(db, rpc)

    reply = await rpc("fulfillment.stock.release", release_body(), headers=RELEASE_HEADERS)

    refs = sorted(first["reservations"], key=lambda r: r["productCode"])  # item (lock) order
    assert reply == {"outcome": "released", "orderReference": ORDER, "released": refs}
    assert {r["status"] for r in await db.reservations(ORDER)} == {"released"}
    assert (await db.stock(COMPANY, "PRD-A1"))["reserved_units"] == 1, "back to before"
    assert (await db.stock(COMPANY, "PRD-B2"))["reserved_units"] == 2
    assert (await db.stock(COMPANY, "PRD-A1"))["units"] == 10, "release does not change on-hand"
    [released] = facts_of(await db.outbox(), "stock.released.v1")
    assert released["aggregate_id"] == ids["PRD-A1"], "the first released reservation's item"
    assert str(released["correlation_id"]) == RELEASE_CORRELATION
    assert str(released["causation_id"]) == RELEASE_REQUEST
    assert released["payload"] == {
        "orderReference": ORDER,
        "companyCode": COMPANY,
        "retailerCode": RETAILER,
        "released": refs,
        "reason": "order_cancelled",
    }
    assert len(facts_of(await db.outbox(), "stock.reserved.v1")) == 1


async def test_the_reason_of_the_released_fact_is_the_requests_whichever_it_is(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)

    await rpc(
        "fulfillment.stock.release", release_body(reason="credit_rejected"), headers=RELEASE_HEADERS
    )

    [released] = facts_of(await db.outbox(), "stock.released.v1")
    assert released["payload"]["reason"] == "credit_rejected"


async def test_r34_answers_success_and_emits_no_second_fact_when_every_reservation_is_already_released(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)
    await rpc("fulfillment.stock.release", release_body(), headers=RELEASE_HEADERS)
    counters = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]
    again_headers = {
        "x-correlation-id": str(uuid.UUID(int=0xE0)),
        "x-request-id": str(uuid.UUID(int=0xE1)),
    }

    again = await rpc("fulfillment.stock.release", release_body(), headers=again_headers)

    assert again == {"outcome": "already_released", "orderReference": ORDER, "released": []}
    after = await db.fetch("SELECT * FROM stock ORDER BY product_code")
    assert [dict(r) for r in after] == counters
    outbox = await db.outbox()
    assert len(facts_of(outbox, "stock.released.v1")) == 1, "no second fact"
    assert all(str(r["correlation_id"]) != str(uuid.UUID(int=0xE0)) for r in outbox)


async def test_fs9_answers_already_released_with_an_empty_list_and_emits_nothing_for_an_order_that_never_held_a_reservation(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])

    reply = await rpc(
        "fulfillment.stock.release", release_body("ORD-000099"), headers=RELEASE_HEADERS
    )

    assert reply == {"outcome": "already_released", "orderReference": "ORD-000099", "released": []}
    assert "released" in reply, "the empty list is WRITTEN, not omitted"
    assert await db.outbox() == []

    # control row: a real release in the same test writes, so the empty outbox above means something
    await rpc("fulfillment.stock.reserve", reserve_body(("PRD-A1", 2)), headers=RESERVE_HEADERS)
    await rpc("fulfillment.stock.release", release_body(), headers=RELEASE_HEADERS)
    assert len(facts_of(await db.outbox(), "stock.released.v1")) == 1


async def test_fs10_replies_precondition_failed_and_emits_nothing_when_the_orders_reservations_are_consumed(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)
    # the despatch's effect (feature 18): the reservations become `consumed` and both counters fall
    await db.execute(
        "UPDATE reservations SET status = 'consumed' WHERE order_reference = $1", ORDER
    )
    await db.execute(
        "UPDATE stock SET units = units - 3, reserved_units = reserved_units - 3"
        " WHERE product_code = 'PRD-A1'"
    )
    await db.execute(
        "UPDATE stock SET units = units - 5, reserved_units = reserved_units - 5"
        " WHERE product_code = 'PRD-B2'"
    )
    before = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]
    rows_before = [dict(r) for r in await db.reservations(ORDER)]

    reply = await rpc("fulfillment.stock.release", release_body(), headers=RELEASE_HEADERS)

    assert reply["code"] == "PRECONDITION_FAILED"
    assert reply["details"] == {"code": "reservation.terminal"}
    assert [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")] == before
    assert sorted(
        (dict(r) for r in await db.reservations(ORDER)), key=lambda r: str(r["id"])
    ) == sorted(rows_before, key=lambda r: str(r["id"]))
    assert facts_of(await db.outbox(), "stock.released.v1") == [], "no released fact"
    # control row: the reserve's own fact is in the outbox, so the outbox read can see rows
    assert len(facts_of(await db.outbox(), "stock.reserved.v1")) == 1


async def test_fs25_a_release_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)
    hold = await db.hold([(COMPANY, "PRD-B2")])  # a stock row of the order, not the first
    try:
        release = asyncio.create_task(
            rpc("fulfillment.stock.release", release_body(), headers=RELEASE_HEADERS, timeout=30)
        )
        # the release is seen UNGRANTED on that row (a locking SELECT waiting on a lock)
        try:
            await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 1, deadline_seconds=10)
        except TimeoutError:
            pytest.fail(
                "the release never waited on the held stock row: no locking SELECT on stock was"
                " seen ungranted, so the release does not take the stock lock (FS25)"
            )
        assert not release.done(), "the release must wait while the test holds the row"
        assert {r["status"] for r in await db.reservations(ORDER)} == {"reserved"}

        await hold.commit()

        reply = await asyncio.wait_for(release, timeout=15)
        assert reply["outcome"] == "released"
    finally:
        await hold.rollback()
    assert {r["status"] for r in await db.reservations(ORDER)} == {"released"}


async def test_a_release_with_an_unknown_reason_is_a_validation_failure(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    reply = await rpc(
        "fulfillment.stock.release", release_body(reason="because"), headers=RELEASE_HEADERS
    )
    assert reply["code"] == "VALIDATION_FAILED"
