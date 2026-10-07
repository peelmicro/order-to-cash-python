# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""Retry, park, resume and the sweeper (R29's retry case, SO3, SO5, SO16).

A stand-in that never replies exercises the in-line policy (three attempts, back-off between them) and
the park; a responder that appears later exercises the sweeper's resumption. SO3 and SO16 commit an
owed `pending` row with NO fast-path signal (written through the unit of work's queue, as a fact's
transaction would, but with no event published), so the only thing that can issue it is a sweeper
cycle. Every wait is on durable evidence: a `saga_commands` row reaching `parked` or `sent`.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from otc_contracts import to_wire_json
from otc_contracts.generated.asyncapi import Line3, StockReserveRequestPayload
from otc_cqrs import Dispatcher
from otc_orders.application.ports.saga_command_store import OwedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import UniqueId

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


async def owe_stock_reserve(uow: SqlAlchemyUnitOfWork, order: Order) -> None:
    """Commit a `pending` stock.reserve row for `order` and publish NOTHING: no signal exists."""
    payload = to_wire_json(
        StockReserveRequestPayload(
            order_reference=order.order_reference.value,
            retailer_code=order.retailer_code,
            company_code=order.company_code,
            lines=[
                Line3(product_code=line.product_code, units=line.quantity.value)
                for line in order.lines
            ],
        )
    )
    async with uow.begin() as transaction:
        await transaction.saga_commands.enqueue(
            OwedCommand(
                order_id=order.id,
                order_reference=order.order_reference.value,
                kind=SagaCommandKind.STOCK_RESERVE,
                payload=payload,
                triggering_event_id=UniqueId(uuid.uuid4()),
            )
        )


async def test_r29_retries_a_timed_out_command_with_backoff_without_changing_the_order_status_and_records_the_exhausted_attempts_durably(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness(SAGA_SWEEPER_ENABLED="false") as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        stand_in.behaviour = saga.behaviours["silent"]  # subscribed, and it never replies
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def parked() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "parked"

        await waits(parked, "the exhausted stock.reserve row is parked")

        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert row is not None
        assert row["attempts"] == 3, "the exhausted attempts are recorded durably"
        assert "no reply within 400 ms" in row["last_error"], row["last_error"]
        assert "fulfillment.stock.reserve" in row["last_error"]
        assert row["next_attempt_at"] is not None, "a retry time is recorded"
        assert row["sent_at"] is None
        assert await saga.db.status_of(order.id) == "placed", "R29: the order status is unchanged"
        requests = stand_in.requests_for(order.id.value)
        assert len(requests) == 3, "exactly MaxAttempts in-line attempts"
        assert len({r.headers["x-request-id"] for r in requests}) == 1, "one request id per row"


async def test_so5_a_parked_command_is_reattempted_by_the_sweeper_and_sent_once_a_responder_appears(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        stand_in.behaviour = saga.behaviours["silent"]
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def parked() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "parked"

        await waits(parked, "the stock.reserve row is parked while no responder answers")

        # the responder appears (and, like the real one, publishes the fact it caused)
        stand_in.behaviour = saga.behaviours["accept_stock_reserve"]
        stand_in.emit = True

        async def resumed() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD)
            return row is not None and row["status"] == "sent"

        await waits(
            resumed, "the next sweep sends the parked row and the saga advances to credit.hold"
        )

        reserve = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert reserve is not None
        assert reserve["status"] == "sent"
        assert reserve["attempts"] == 3, "the attempts of the parked cycle stay on the row"
        assert reserve["sent_at"] is not None
        assert await saga.db.status_of(order.id) == "stock_reserved"


async def test_so3_a_pending_row_committed_with_no_fast_path_signal_is_issued_by_a_sweeper_cycle_and_the_saga_resumes(
    saga_harness: Any, order_at: OrderAt, uow: SqlAlchemyUnitOfWork, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        saga.stand_in(SagaCommandKind.STOCK_RESERVE).emit = True
        await owe_stock_reserve(uow, order)  # committed pending, and nobody signals

        async def resumed() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD)
            return row is not None and row["status"] == "sent"

        await waits(resumed, "a sweeper cycle issues the row and the saga moves on to credit.hold")

        reserve = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert reserve is not None
        assert reserve["status"] == "sent"
        assert await saga.db.status_of(order.id) == "stock_reserved"


async def test_so16_the_sweeper_issues_each_row_it_claimed_exactly_once_without_reclaiming_it(
    saga_harness: Any, order_at: OrderAt, uow: SqlAlchemyUnitOfWork, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        # fast path disabled for this row: it is committed with no signal, so only the sweeper can
        # issue it, and the sweeper holds the lease on it while it does
        await owe_stock_reserve(uow, order)

        async def sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "sent"

        await waits(sent, "the sweeper's own claim is issued and the row reaches sent")

        requests = saga.stand_in(SagaCommandKind.STOCK_RESERVE).requests_for(order.id.value)
        assert len(requests) == 1, (
            "exactly one request: issued once, from the claim the sweeper holds"
        )


async def test_the_sweeper_issues_commands_without_the_fast_path_or_the_cqrs_dispatcher(
    saga_harness: Any,
    order_at: OrderAt,
    uow: SqlAlchemyUnitOfWork,
    waits: Waits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweeper is the durability backstop: it must not depend on the layers it backs up."""
    order = await order_at(OrderStatus.PLACED)

    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the sweeper path went through the otc_cqrs dispatcher")

    async with saga_harness(SAGA_CONSUMER_ENABLED="false") as saga:
        fast_path = saga.runtime.tasks["saga-fast-path"]
        fast_path.cancel()  # the fast path is stopped: a signal to it is dropped
        await asyncio.wait({fast_path}, timeout=5)
        monkeypatch.setattr(Dispatcher, "publish", forbidden)
        monkeypatch.setattr(Dispatcher, "send", forbidden)

        await owe_stock_reserve(uow, order)

        async def sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "sent"

        await waits(sent, "the sweeper alone issues the due pending row")

        assert len(saga.stand_in(SagaCommandKind.STOCK_RESERVE).requests_for(order.id.value)) == 1
