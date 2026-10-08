"""SA-4's despatch half: `despatch.create` versus `stock.release` on one order, in BOTH outcomes.

Both requests take the same lock (the stock rows of the order, then its reservations), so two
transactions on one order serialise on the first stock row and whichever commits second decides on
the first's COMMITTED reservations. Each ordering is CONSTRUCTED, never repeated until it happens:
the test holds the stock row, sends the request that must win, waits until it is observed UNGRANTED
on that row (`pg_stat_activity`), sends the request that must lose, waits until THAT one is observed
ungranted too, and only then releases the row. Row-lock waiters are served in arrival order, so the
first request to queue is the first to run.

* release wins -> the despatch finds nothing to consume (`PRECONDITION_FAILED`, no advice, no fact);
* despatch wins -> the release answers `PRECONDITION_FAILED` (the reservations are `consumed`).

The failure message names the claim: a despatch (or release) that never queued on the held row does
not take the SA-4 lock (the arm that removes the lock call fails here, at the wait, not later).
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
DESPATCH_HEADERS = {
    "x-correlation-id": str(uuid.UUID(int=0xD0D0)),
    "x-request-id": str(uuid.UUID(int=0xDA05)),
}
RELEASE_HEADERS = {
    "x-correlation-id": str(uuid.UUID(int=0xE0E0)),
    "x-request-id": str(uuid.UUID(int=0xEA05)),
}
DESPATCH = "fulfillment.despatch.create"
RELEASE = "fulfillment.stock.release"
LOCKING_SELECT = "SELECT%FROM stock%FOR UPDATE%"


async def reserved_order(db: Any, rpc: Any) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 1, 3), ("PRD-B2", 20, 2, 3)])
    reply = await rpc(
        "fulfillment.stock.reserve",
        {
            "orderReference": ORDER,
            "retailerCode": RETAILER,
            "companyCode": COMPANY,
            "lines": [
                {"productCode": "PRD-A1", "units": 3},
                {"productCode": "PRD-B2", "units": 5},
            ],
        },
        headers=RESERVE_HEADERS,
    )
    assert reply["outcome"] == "accepted"


async def queue_in_order(
    db: Any, rpc: Any, first: tuple[str, dict[str, Any], dict[str, str]], second: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hold the first stock row; queue `first`, then `second`, each seen UNGRANTED; release the row;
    return their replies in that order."""
    hold = await db.hold([(COMPANY, "PRD-A1")])
    try:
        winner = asyncio.create_task(rpc(first[0], first[1], headers=first[2], timeout=30))
        try:
            await db.wait_for_lock_waiters(LOCKING_SELECT, 1, deadline_seconds=10)
        except TimeoutError:
            pytest.fail(f"{first[0]} never waited on the held stock row: it does not take the lock")
        loser_subject, loser_body, loser_headers = second
        loser = asyncio.create_task(
            rpc(loser_subject, loser_body, headers=loser_headers, timeout=30)
        )
        try:
            await db.wait_for_lock_waiters(LOCKING_SELECT, 2, deadline_seconds=10)
        except TimeoutError:
            pytest.fail(
                f"{loser_subject} never waited on the held stock row: it does not take the SA-4"
                " lock, so it is not serialised with the other request on the order"
            )
        assert not winner.done()
        assert not loser.done()
        await hold.commit()
        return await asyncio.wait_for(winner, timeout=15), await asyncio.wait_for(loser, timeout=15)
    finally:
        await hold.rollback()


async def test_sa4_release_wins_the_despatch_finds_nothing_to_consume_and_creates_no_advice(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)

    release, despatch = await queue_in_order(
        db,
        rpc,
        (RELEASE, {"orderReference": ORDER, "reason": "order_cancelled"}, RELEASE_HEADERS),
        (DESPATCH, {"orderReference": ORDER}, DESPATCH_HEADERS),
    )

    assert release["outcome"] == "released"
    assert despatch["code"] == "PRECONDITION_FAILED"
    assert despatch["details"] == {"orderReference": ORDER}
    assert {r["status"] for r in await db.reservations(ORDER)} == {"released"}
    assert await db.fetch("SELECT * FROM despatches") == [], "no advice"
    a1, b2 = await db.stock(COMPANY, "PRD-A1"), await db.stock(COMPANY, "PRD-B2")
    assert (a1["units"], a1["reserved_units"]) == (10, 1), "released, not consumed: on-hand intact"
    assert (b2["units"], b2["reserved_units"]) == (20, 2)
    types = [r["event_type"] for r in await db.outbox()]
    assert types == ["stock.reserved.v1", "stock.released.v1"], "no despatched fact"
    assert await db.fetch("SELECT * FROM despatch_number_sequences") == [], "no number burned"


async def test_sa4_despatch_wins_the_release_answers_precondition_failed_and_changes_nothing(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)

    despatch, release = await queue_in_order(
        db,
        rpc,
        (DESPATCH, {"orderReference": ORDER}, DESPATCH_HEADERS),
        (RELEASE, {"orderReference": ORDER, "reason": "order_cancelled"}, RELEASE_HEADERS),
    )

    assert despatch["created"] is True
    assert release["code"] == "PRECONDITION_FAILED"
    assert release["details"] == {"code": "reservation.terminal"}
    assert {r["status"] for r in await db.reservations(ORDER)} == {"consumed"}
    a1, b2 = await db.stock(COMPANY, "PRD-A1"), await db.stock(COMPANY, "PRD-B2")
    assert (a1["units"], a1["reserved_units"]) == (7, 1), "consumed, and not released on top"
    assert (b2["units"], b2["reserved_units"]) == (15, 2)
    types = [r["event_type"] for r in await db.outbox()]
    assert types == ["stock.reserved.v1", "order.despatched.v1"], "no released fact"
    assert len(await db.fetch("SELECT * FROM despatches")) == 1


async def test_fs25_a_despatch_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    # The despatch half of FS25's lock test (#8 id 79): the release's own is in
    # `test_stock_release_idempotency.py`. A test connection holds the order's SECOND stock row; the
    # despatch must be seen ungranted on it, and consumes only after the row is released.
    await reserved_order(db, rpc)
    hold = await db.hold([(COMPANY, "PRD-B2")])
    try:
        despatch = asyncio.create_task(
            rpc(DESPATCH, {"orderReference": ORDER}, headers=DESPATCH_HEADERS, timeout=30)
        )
        try:
            await db.wait_for_lock_waiters(LOCKING_SELECT, 1, deadline_seconds=10)
        except TimeoutError:
            pytest.fail(
                "the despatch never waited on the held stock row: no locking SELECT on stock was"
                " seen ungranted, so the despatch does not take the SA-4 lock (FS25)"
            )
        assert not despatch.done(), "the despatch must wait while the test holds the row"
        assert {r["status"] for r in await db.reservations(ORDER)} == {"reserved"}

        await hold.commit()

        reply = await asyncio.wait_for(despatch, timeout=15)
        assert reply["created"] is True
    finally:
        await hold.rollback()
    assert {r["status"] for r in await db.reservations(ORDER)} == {"consumed"}
