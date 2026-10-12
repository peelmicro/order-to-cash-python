# ruff: noqa: E501 - test names are the sentences the acceptance items and the spec use
"""A `credit.approved.v1` that arrives after the operator's cancellation was accepted (`saga.md` 4.3,
"A credit approval that arrives after the cancellation").

The hold was acquired, so it is unwound: `credit.release` and NOTHING else. No transition, no
`order.confirmed.v1`, no `despatch.create`. The two shapes the spec names are both driven (still
`stock_reserved` with the stock release under way; already `cancelled` with `operator_cancelled`),
and so are the cancellations the saga decided itself, which must NOT be treated as one.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from otc_contracts.generated.asyncapi import Reason1, Reason3
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


async def ask_cancel(client: Any, order: Order, note: str) -> dict[str, Any]:
    reply = await client.request(
        "orders.cancel",
        json.dumps(
            {"orderId": str(order.id.value), "reason": "operator_cancelled", "note": note}
        ).encode(),
        timeout=10,
        headers={"x-correlation-id": str(order.id.value), "x-request-id": str(uuid.uuid4())},
    )
    answer: dict[str, Any] = json.loads(reply.data)
    return answer


async def credit_release_sent(saga: Any, order: Order, waits: Waits) -> None:
    async def sent() -> bool:
        row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_RELEASE)
        return row is not None and row["status"] == "sent"

    await waits(sent, "the credit.release row reaches sent")


async def ignored_as_unmet(saga: Any, order: Order, fact_id: uuid.UUID, waits: Waits) -> None:
    async def recorded() -> bool:
        return any(
            row["event_id"] == fact_id and row["marker"] == "precondition_unmet"
            for row in await saga.db.ignored(order.id, "credit.approved.v1")
        )

    await waits(recorded, "credit.approved.v1 is recorded as a precondition_unmet fact")


async def test_a_late_credit_approval_while_the_stock_release_is_under_way_issues_credit_release_and_nothing_else(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        stock = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        stock.behaviour = saga.behaviours["silent"]  # the release is "under way" and unanswered
        await ask_cancel(nats_client, order, "$late approval")

        await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await credit_release_sent(saga, order, waits)

        [credit_request] = saga.stand_in(SagaCommandKind.CREDIT_RELEASE).requests_for(
            order.id.value
        )
        assert set(credit_request.request) == {"orderReference", "retailerCode", "companyCode"}
        assert credit_request.request["orderReference"] == order.order_reference.value
        assert await saga.db.status_of(order.id) == "stock_reserved", "no transition"
        assert await saga.db.outbox_types(order.id) == [], "no order.confirmed.v1, nothing emitted"
        assert saga.stand_in(SagaCommandKind.DESPATCH_CREATE).requests == [], "no despatch.create"
        assert await saga.db.command_row(order.id, SagaCommandKind.DESPATCH_CREATE) is None

        # the stock release then completes the cancellation: the late credit.release is NOT one of
        # its recorded compensation steps (saga.md 4.3), and the note survived the detour
        await saga.publish_fact(
            "stock.released.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
            release_reason=Reason1.order_cancelled,
        )

        async def cancelled() -> bool:
            return "order.cancelled.v1" in await saga.db.outbox_types(order.id)

        await waits(cancelled, "the stock release fact cancels the order")
        payload = json.loads(
            await saga.db.fetchval(
                "SELECT payload::text FROM outbox WHERE aggregate_id = $1 "
                "AND event_type = 'order.cancelled.v1'",
                order.id.value,
            )
        )
        assert payload["note"] == "$late approval"
        assert [step["step"] for step in payload["compensationSteps"]] == ["stock_released"]


async def test_a_late_credit_approval_after_the_operator_cancellation_completed_issues_credit_release_and_nothing_else(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await credit_release_sent(saga, order, waits)

        assert len(saga.stand_in(SagaCommandKind.CREDIT_RELEASE).requests_for(order.id.value)) == 1
        assert await saga.db.status_of(order.id) == "cancelled"
        assert await saga.db.outbox_types(order.id) == []
        assert [r["command"] for r in await saga.db.command_rows(order.id)] == ["credit.release"]
        assert saga.stand_in(SagaCommandKind.DESPATCH_CREATE).requests == []


@pytest.mark.parametrize(
    "reason", [CancellationReason.CREDIT_REJECTED, CancellationReason.STOCK_REJECTED]
)
async def test_a_credit_approval_for_a_cancellation_the_saga_decided_is_ignored_and_releases_nothing(
    reason: CancellationReason, saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=reason)
    async with saga_harness() as saga:
        fact_id = await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await ignored_as_unmet(saga, order, fact_id, waits)

        assert await saga.db.command_rows(order.id) == [], "no credit.release for this one"
        assert all(not s.requests for s in saga.stand_ins.values())
        assert await saga.db.outbox_types(order.id) == []


async def test_a_credit_approval_beside_the_sagas_own_credit_rejected_release_is_not_a_late_approval(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    """The query's `reason` narrowing at the saga level: a `stock.release` row exists for the order,
    but its request says `credit_rejected`, so no operator cancellation was accepted. (Billing never
    answers both; the fixture is the decoy that proves the branch looks at the REASON.)"""
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        saga.stand_in(SagaCommandKind.STOCK_RELEASE).behaviour = saga.behaviours["silent"]
        await saga.publish_fact(
            "credit.rejected.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def release_owed() -> bool:
            return await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE) is not None

        await waits(release_owed, "the credit rejection owes stock.release")
        await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def confirmed() -> bool:
            return bool(await saga.db.status_of(order.id) == "confirmed")

        await waits(confirmed, "the generic path decided: the approval confirms the order")
        assert await saga.db.command_row(order.id, SagaCommandKind.CREDIT_RELEASE) is None


async def test_the_credit_released_fact_after_a_late_approval_cancel_is_ignored_not_a_second_cancel(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    async with saga_harness() as saga:
        fact_id = await saga.publish_fact(
            "credit.released.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
            credit_release_reason=Reason3.order_cancelled,
        )

        async def recorded() -> bool:
            return any(
                row["event_id"] == fact_id
                for row in await saga.db.ignored(order.id, "credit.released.v1")
            )

        await waits(recorded, "credit.released.v1 is recorded as ignored")
        assert await saga.db.outbox_types(order.id) == []


async def test_a_late_credit_approval_is_issued_by_the_fast_path_alone_with_the_sweeper_disabled(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    async with saga_harness(SAGA_SWEEPER_ENABLED="false") as saga:
        await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        await credit_release_sent(saga, order, waits)


async def test_a_despatch_fact_after_the_operator_cancellation_completed_is_ignored_and_issues_no_invoice(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    async with saga_harness() as saga:
        fact_id = await saga.publish_fact(
            "order.despatched.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def recorded() -> bool:
            return any(
                row["event_id"] == fact_id and row["marker"] == "precondition_unmet"
                for row in await saga.db.ignored(order.id, "order.despatched.v1")
            )

        await waits(recorded, "order.despatched.v1 is recorded as a precondition_unmet fact")
        assert await saga.db.command_rows(order.id) == [], "no invoice.issue for a cancelled order"
        assert await saga.db.status_of(order.id) == "cancelled"
