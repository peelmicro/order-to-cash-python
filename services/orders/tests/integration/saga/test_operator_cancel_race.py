# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""The operator cancel against the saga's forward progress, BOTH outcomes (#8 id 62, #7's F1).

A cancel reads an order's status and enqueues its compensation in one transaction while the saga
advances the same order in another. Neither outcome is produced by repetition: a third connection
HOLDS the order's row lock, the two writers are started one after the other and each is observed
WAITING on that lock (`pg_stat_activity`: `wait_event_type = 'Lock'`), and only then is the lock
released. PostgreSQL queues row-lock waiters in the order they arrived, so the order of the two starts
IS the order of the two commits, and the end state of each is asserted:

* cancel first -> the saga's `credit.approved.v1` finds the accepted cancellation: `credit.release`
  and NOTHING else (no `order.confirmed.v1`, no `despatch.create`);
* saga first -> the order is `confirmed` when the cancel gets the lock: the two-hop plan, a
  `despatch.create` already owed, the stock released first so that Fulfillment decides.

The cancel takes the lock with `get_by_id_for_update` (SO17). Remove it and the cancel does not
wait: the first observation below fails, naming the claim.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]

# `pg_stat_activity.query` is cut at `track_activity_query_size` (1024 bytes), which drops the
# trailing `FOR UPDATE OF orders` of the repository's order load, so the statement is recognised by
# its beginning: the order load is the only statement of the service that starts like this, and the
# claim being observed is "this backend waits on a Lock".
WAITING_FOR_THE_ORDER_ROW = """
SELECT count(*) FROM pg_stat_activity
 WHERE datname = current_database() AND wait_event_type = 'Lock'
   AND query LIKE 'SELECT orders.id, orders.order_reference%'
"""


@asynccontextmanager
async def held_order_lock(dsn: str, order: Order) -> AsyncIterator[Callable[[], Awaitable[None]]]:
    """A third connection that holds `FOR UPDATE` on the order's row until `release()` is called."""
    connection = await asyncpg.connect(dsn)
    transaction = connection.transaction()
    await transaction.start()
    released = False

    async def release() -> None:
        nonlocal released
        released = True
        await transaction.commit()

    try:
        await connection.fetchval("SELECT id FROM orders WHERE id = $1 FOR UPDATE", order.id.value)
        yield release
    finally:
        if not released:
            await transaction.rollback()
        await connection.close()


async def ask_cancel(client: Any, order: Order) -> dict[str, Any]:
    reply = await client.request(
        "orders.cancel",
        json.dumps(
            {"orderId": str(order.id.value), "reason": "operator_cancelled", "note": "$race"}
        ).encode(),
        timeout=15,
        headers={"x-correlation-id": str(order.id.value), "x-request-id": str(uuid.uuid4())},
    )
    answer: dict[str, Any] = json.loads(reply.data)
    return answer


def waiting_exactly(saga: Any, count: int) -> Callable[[], Awaitable[bool]]:
    async def predicate() -> bool:
        return int(await saga.db.fetchval(WAITING_FOR_THE_ORDER_ROW)) == count

    return predicate


async def test_outcome_one_the_cancel_takes_the_lock_first_so_the_late_credit_approval_releases_the_hold_and_advances_nothing(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any, migrated_db: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga, held_order_lock(migrated_db.dsn, order) as release:
        cancel = asyncio.create_task(ask_cancel(nats_client, order))
        await waits(waiting_exactly(saga, 1), "the cancel is waiting on the order row lock (SO17)")
        await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await waits(
            waiting_exactly(saga, 2), "the saga's credit.approved step is waiting behind the cancel"
        )

        await release()
        reply = await cancel

        assert reply["status"] == "stock_reserved", "the cancel saw the order as the saga left it"
        assert reply["compensationPlanned"] == ["stock_release"]

        async def credit_release_owed() -> bool:
            return await saga.db.command_row(order.id, SagaCommandKind.CREDIT_RELEASE) is not None

        await waits(credit_release_owed, "the late approval owes credit.release")
        assert await saga.db.status_of(order.id) == "stock_reserved", "no transition"
        assert "order.confirmed.v1" not in await saga.db.outbox_types(order.id)
        assert await saga.db.command_row(order.id, SagaCommandKind.DESPATCH_CREATE) is None, (
            "no despatch.create"
        )
        assert sorted(r["command"] for r in await saga.db.command_rows(order.id)) == [
            "credit.release",
            "stock.release",
        ]


async def test_outcome_two_the_saga_step_takes_the_lock_first_so_the_cancel_plans_stock_then_credit_from_confirmed(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any, migrated_db: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga, held_order_lock(migrated_db.dsn, order) as release:
        await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await waits(waiting_exactly(saga, 1), "the saga's credit.approved step is waiting")
        cancel = asyncio.create_task(ask_cancel(nats_client, order))
        await waits(waiting_exactly(saga, 2), "the cancel is waiting on the order row lock (SO17)")

        await release()
        reply = await cancel

        assert reply["status"] == "confirmed", "the cancel found the order the saga had advanced"
        assert reply["compensationPlanned"] == ["stock_release", "credit_release"]
        assert await saga.db.status_of(order.id) == "confirmed"
        assert "order.confirmed.v1" in await saga.db.outbox_types(order.id)
        rows = {r["command"]: r for r in await saga.db.command_rows(order.id)}
        assert set(rows) == {"despatch.create", "stock.release"}
        assert rows["stock.release"]["operator_note"] == "$race"
        assert json.loads(rows["stock.release"]["payload"])["reason"] == "order_cancelled"
