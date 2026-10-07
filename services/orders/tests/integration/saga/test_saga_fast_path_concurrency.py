# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""A command whose responder never answers delays no other order's command (SO13; #8 ids 80, 89).

Through the REAL lifespan, real NATS and the real table, with the sweeper DISABLED so that only the
fast path can issue anything: order A's `credit.hold` is never answered (its dispatch sits in the
fast path for ~3 x TimeoutMs), and order B's `stock.reserve`, owed AFTER A's command was signalled,
must still reach `sent` within a bound shorter than ONE TimeoutMs, while A's row is still unsent. A
single sequential drain loop fails this by name (order B and the bound).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]

TIMEOUT_MS = 3000
BOUND_SECONDS = 1.5  # shorter than ONE TimeoutMs


async def test_so13_a_command_whose_responder_never_answers_does_not_delay_another_orders_command(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order_a = await order_at(OrderStatus.PLACED)
    order_b = await order_at(OrderStatus.PLACED)
    async with saga_harness(
        SAGA_SWEEPER_ENABLED="false",
        SAGA_COMMAND_TIMEOUT_MS=str(TIMEOUT_MS),
        SAGA_COMMAND_LEASE_MS="60000",
    ) as saga:
        hold = saga.stand_in(SagaCommandKind.CREDIT_HOLD)
        accept = saga.behaviours["accept_credit_hold"]
        hold.behaviour = lambda recorded: (
            None
            if recorded.request["orderReference"] == order_a.order_reference.value
            else accept(recorded)
        )

        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order_a.id.value,
            reference=order_a.order_reference.value,
        )

        async def a_is_being_issued() -> bool:
            return bool(hold.requests_for(order_a.id.value))

        await waits(
            a_is_being_issued,
            "order A's credit.hold request reached the responder that never answers",
        )

        started = time.monotonic()
        await saga.publish_fact(
            "order.placed.v1",
            correlation_id=order_b.id.value,
            reference=order_b.order_reference.value,
        )

        async def b_is_sent() -> bool:
            row = await saga.db.command_row(order_b.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "sent"

        await waits(
            b_is_sent,
            f"order B's stock.reserve is sent within {BOUND_SECONDS}s although order A's credit.hold "
            "is still being issued (a bound shorter than one TimeoutMs)",
            seconds=BOUND_SECONDS,
        )
        elapsed = time.monotonic() - started

        row_a = await saga.db.command_row(order_a.id, SagaCommandKind.CREDIT_HOLD)
        assert row_a is not None
        assert row_a["status"] == "pending", "A's row is still unsent while B's is done"
        assert elapsed < TIMEOUT_MS / 1000, f"B took {elapsed:.2f}s, not less than one TimeoutMs"
        print(f"SO13 integration: order B sent {elapsed:.2f}s after publish (A still unsent)")
        await asyncio.sleep(0)
