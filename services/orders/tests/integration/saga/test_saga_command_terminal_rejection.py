# ruff: noqa: E501 - test names are the literal names the feature's acceptance items assign
"""Feature 42 end to end: a real NATS responder answering an `RpcError` to a saga command.

A terminal business code resolves the `saga_commands` row to `rejected` on the FIRST attempt, and the
running sweeper never touches it again; a transient code is retried exactly as feature 16 built it
(three in-line attempts, then `parked`). Every wait is on durable evidence: a row's status.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


def rpc_error(code: str) -> Callable[[Any], bytes]:
    def reply(_recorded: Any) -> bytes:
        return json.dumps({"code": code, "message": f"responder said {code}"}).encode()

    return reply


async def test_feature_42_a_terminal_rpc_error_resolves_the_row_to_rejected_on_the_first_attempt_and_the_sweeper_never_re_issues_it(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:  # the sweeper runs every 100 ms
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        stand_in.behaviour = rpc_error("STOCK_UNAVAILABLE")
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def rejected() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "rejected"

        await waits(rejected, "the stock.reserve row is resolved to rejected")

        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert row is not None
        assert row["attempts"] == 1, "resolved on the first attempt"
        assert "STOCK_UNAVAILABLE" in row["last_error"], row["last_error"]
        assert row["next_attempt_at"] is None
        assert row["sent_at"] is None
        assert await saga.db.status_of(order.id) == "placed", "the order status is unchanged"
        assert len(stand_in.requests_for(order.id.value)) == 1, "never retried in line"

        await asyncio.sleep(1.5)  # fifteen sweeper cycles and past the pending grace window

        again = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert again is not None
        assert again["status"] == "rejected"
        assert len(stand_in.requests_for(order.id.value)) == 1, "the sweeper never re-issues it"


async def test_feature_42_a_transient_rpc_error_is_still_retried_in_line_and_parked(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness(SAGA_SWEEPER_ENABLED="false") as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        stand_in.behaviour = rpc_error("INTERNAL_ERROR")
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def parked() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "parked"

        await waits(parked, "the transient-failing stock.reserve row is parked")

        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert row is not None
        assert row["attempts"] == 3
        assert "INTERNAL_ERROR" in row["last_error"]
        assert len(stand_in.requests_for(order.id.value)) == 3, (
            "exactly MaxAttempts in-line attempts"
        )
