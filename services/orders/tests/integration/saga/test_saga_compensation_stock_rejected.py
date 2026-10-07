# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""Path A: `stock.rejected.v1` cancels and issues NO `stock.release` (R26; `design.md` 10).

The "shall not" is proven at the wire: the `fulfillment.stock.release` stand-in records zero requests
and no `saga_commands` row exists, after the first delivery AND after a redelivery (a new event id)
against the now-cancelled order, sampled only once that redelivery's `saga_ignored_facts` row exists
(#7 D3: its wire-level R26 case survived the mutation the unit cases killed).
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


async def test_r26_cancels_with_reason_stock_rejected_and_issues_no_stock_release_command(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        rejected = await saga.publish_fact(
            "stock.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def cancelled() -> bool:
            return "order.cancelled.v1" in await saga.db.outbox_types(order.id)

        await waits(cancelled, "an order.cancelled.v1 outbox row exists")

        assert await saga.db.status_of(order.id) == "cancelled"
        assert (
            await saga.db.fetchval(
                "SELECT cancellation_reason FROM orders WHERE id = $1", order.id.value
            )
            == "stock_rejected"
        )
        payload = json.loads(
            await saga.db.fetchval(
                "SELECT payload::text FROM outbox WHERE aggregate_id = $1 "
                "AND event_type = 'order.cancelled.v1'",
                order.id.value,
            )
        )
        assert payload["cancellationReason"] == "stock_rejected"
        assert payload["compensationSteps"] == [], (
            "reservation is all-or-nothing: nothing to release"
        )
        causation = await saga.db.fetchval(
            "SELECT causation_id FROM outbox WHERE aggregate_id = $1", order.id.value
        )
        assert causation == rejected
        assert saga.stand_in(SagaCommandKind.STOCK_RELEASE).requests == [], "zero release requests"
        assert await saga.db.command_rows(order.id) == [], "and no stock.release row"

        # a redelivery with a NEW event id against the cancelled order: ignored, still no release
        again = await saga.publish_fact(
            "stock.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def second_recorded() -> bool:
            return any(
                row["event_id"] == again
                for row in await saga.db.ignored(order.id, "stock.rejected.v1")
            )

        await waits(second_recorded, "the redelivery's precondition_unmet row exists")

        assert saga.stand_in(SagaCommandKind.STOCK_RELEASE).requests == []
        assert await saga.db.command_rows(order.id) == []
        assert (await saga.db.outbox_types(order.id)).count("order.cancelled.v1") == 1
