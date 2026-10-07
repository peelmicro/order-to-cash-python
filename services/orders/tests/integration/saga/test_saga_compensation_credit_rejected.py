# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""Path B: `credit.rejected.v1` releases the stock, THEN the release fact cancels (R27, R28, SO6, SO7).

The cancel is asserted from the outbox row the saga wrote (its `causationId` is the release fact's
event id, R12), never from arrival order. Facts are published by the test, one at a time, so each
step is observed before the next is allowed to happen.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from otc_contracts.generated.asyncapi import Reason1
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


async def test_r27_issues_stock_release_as_the_first_compensation_step_and_leaves_the_order_in_stock_reserved(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "credit.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def release_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
            return row is not None and row["status"] == "sent"

        await waits(release_sent, "the stock.release row reaches sent")

        assert await saga.db.status_of(order.id) == "stock_reserved", (
            "R27: the status stays stock_reserved while the release is being issued"
        )
        [recorded] = saga.stand_in(SagaCommandKind.STOCK_RELEASE).requests_for(order.id.value)
        assert recorded.request == {"orderReference": "ORD-000101", "reason": "credit_rejected"}
        assert "order.cancelled.v1" not in await saga.db.outbox_types(order.id)


async def test_r28_cancels_with_reason_credit_rejected_only_after_stock_released_v1_arrives(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "credit.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def release_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
            return row is not None and row["status"] == "sent"

        await waits(release_sent, "the stock.release is issued")
        # the release command was issued and answered, and the cancel has NOT happened: the cancel
        # waits for the release FACT (R28), not for the credit rejection or the command's reply
        assert await saga.db.status_of(order.id) == "stock_reserved"
        assert "order.cancelled.v1" not in await saga.db.outbox_types(order.id)

        release_row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
        assert release_row is not None
        released = await saga.publish_fact(
            "stock.released.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            causation_id=uuid.UUID(
                int=release_row["id"].int
            ),  # the request id, as a real responder
        )

        async def cancelled() -> bool:
            return "order.cancelled.v1" in await saga.db.outbox_types(order.id)

        await waits(cancelled, "an order.cancelled.v1 outbox row exists")

        assert await saga.db.status_of(order.id) == "cancelled"
        assert (
            await saga.db.fetchval(
                "SELECT cancellation_reason FROM orders WHERE id = $1", order.id.value
            )
            == "credit_rejected"
        )
        causation = await saga.db.fetchval(
            "SELECT causation_id FROM outbox WHERE aggregate_id = $1 "
            "AND event_type = 'order.cancelled.v1'",
            order.id.value,
        )
        assert causation == released, "R12: the cancel is caused by the release fact"


async def test_so6_a_business_rejected_credit_hold_is_marked_sent_and_never_retried(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        saga.stand_in(SagaCommandKind.CREDIT_HOLD).behaviour = saga.behaviours["reject_credit"]
        await saga.publish_fact(
            "stock.reserved.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def hold_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD)
            return row is not None and row["status"] == "sent"

        await waits(hold_sent, "the rejected credit.hold row is marked sent")

        assert len(saga.stand_in(SagaCommandKind.CREDIT_HOLD).requests_for(order.id.value)) == 1, (
            "a business rejection is a reply: exactly one request, never retried"
        )
        row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD)
        assert row is not None
        assert row["attempts"] == 0
        assert await saga.db.status_of(order.id) == "stock_reserved", (
            "the status is unchanged until the rejection FACT arrives"
        )


async def test_so7_the_cancellation_carries_exactly_one_stock_released_step_built_from_the_observed_fact(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        released = await saga.publish_fact(
            "stock.released.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def cancelled() -> bool:
            return "order.cancelled.v1" in await saga.db.outbox_types(order.id)

        await waits(cancelled, "an order.cancelled.v1 outbox row exists")

        payload = json.loads(
            await saga.db.fetchval(
                "SELECT payload::text FROM outbox WHERE aggregate_id = $1 "
                "AND event_type = 'order.cancelled.v1'",
                order.id.value,
            )
        )
        [step] = payload["compensationSteps"]
        assert step["step"] == "stock_released"
        assert step["eventId"] == str(released), "built from the OBSERVED fact's own event id"
        assert step["eventType"] == "stock.released.v1"
        assert payload["cancellationReason"] == "credit_rejected"
        assert "summary" not in step, "gate point G2: #8's value, no summary"


async def test_the_order_cancelled_release_reason_cancels_with_operator_cancelled_and_one_step(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    """The `order_cancelled` branch has NO producer until feature 41 (`orders.cancel`): a stand-in
    publishes the fact, so the branch is driven end to end and not only by a unit case."""
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        released = await saga.publish_fact(
            "stock.released.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            release_reason=Reason1.order_cancelled,
        )

        async def cancelled() -> bool:
            return "order.cancelled.v1" in await saga.db.outbox_types(order.id)

        await waits(cancelled, "an order.cancelled.v1 outbox row exists")

        assert (
            await saga.db.fetchval(
                "SELECT cancellation_reason FROM orders WHERE id = $1", order.id.value
            )
            == "operator_cancelled"
        )
        payload = json.loads(
            await saga.db.fetchval(
                "SELECT payload::text FROM outbox WHERE aggregate_id = $1 "
                "AND event_type = 'order.cancelled.v1'",
                order.id.value,
            )
        )
        assert payload["cancellationReason"] == "operator_cancelled"
        assert [step["eventId"] for step in payload["compensationSteps"]] == [str(released)]
