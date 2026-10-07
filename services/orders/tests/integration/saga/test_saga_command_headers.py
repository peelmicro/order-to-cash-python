# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""Every attempt carries the order id and ONE request id per command row, on both paths (SO14).

A stand-in leaves the first attempt of each row unanswered and answers the second, so each row is
sent twice; both recorded requests must carry `x-correlation-id` = the order id and the SAME
`x-request-id` = the `saga_commands.id` of the row the DATABASE holds. First for a row issued by the
fast path, then for a row issued by the sweeper (committed with no signal).
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from otc_contracts import to_wire_json
from otc_contracts.generated.asyncapi import Line3, StockReserveRequestPayload
from otc_orders.application.ports.saga_command_store import OwedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import UniqueId

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


async def test_so14_every_attempt_carries_the_order_id_and_one_request_id_per_command_row_on_both_paths(
    saga_harness: Any, order_at: OrderAt, uow: SqlAlchemyUnitOfWork, waits: Waits
) -> None:
    fast_order = await order_at(OrderStatus.PLACED)
    sweeper_order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        accept = saga.behaviours["accept_stock_reserve"]
        seen: dict[str, int] = {}

        def silent_first_then_accept(recorded: Any) -> bytes | None:
            key = recorded.headers["x-correlation-id"]
            seen[key] = seen.get(key, 0) + 1
            return None if seen[key] == 1 else accept(recorded)

        stand_in.behaviour = silent_first_then_accept

        # the fast path: a fact owes the command and the event signals it
        await saga.publish_fact(
            "order.placed.v1",
            correlation_id=fast_order.id.value,
            reference=fast_order.order_reference.value,
        )
        # the sweeper path: a row committed with no signal at all
        async with uow.begin() as transaction:
            await transaction.saga_commands.enqueue(
                OwedCommand(
                    order_id=sweeper_order.id,
                    order_reference=sweeper_order.order_reference.value,
                    kind=SagaCommandKind.STOCK_RESERVE,
                    payload=to_wire_json(
                        StockReserveRequestPayload(
                            order_reference=sweeper_order.order_reference.value,
                            retailer_code="RET-01",
                            company_code="CMP-01",
                            lines=[Line3(product_code="SKU-A", units=3)],
                        )
                    ),
                    triggering_event_id=UniqueId(uuid.uuid4()),
                )
            )

        for order in (fast_order, sweeper_order):

            async def sent(order: Order = order) -> bool:
                row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
                return row is not None and row["status"] == "sent"

            await waits(sent, f"{order.order_reference.value}'s stock.reserve row reaches sent")

            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            assert row is not None
            requests = stand_in.requests_for(order.id.value)
            assert len(requests) == 2, "the first attempt was unanswered, the second answered"
            for recorded in requests:
                assert recorded.headers["x-correlation-id"] == str(order.id)
                assert recorded.headers["x-request-id"] == str(row["id"]), (
                    "the request id is the saga_commands row id, unchanged across retries"
                )
