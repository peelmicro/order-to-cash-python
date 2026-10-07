# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""The saga's happy path against stand-in responders (R19-R24, acceptance item 1).

Every case starts from an order at the step's own precondition status (planted through the real
repository, no outbox rows) and publishes the ONE fact that moves it, so each case proves its own
row of saga.md 3.1 and nothing an earlier case left behind. R19 starts from a placed order whose
`order.placed.v1` the real relay publishes. Each step is asserted from durable evidence: the next
command's row reaching `sent`, or an `outbox` row; never a transient status.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated.asyncapi import StockReserveRequestPayload
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


async def test_r19_issues_stock_reserve_for_every_line_on_order_placed_v1_and_leaves_the_order_in_placed(
    saga_harness: Any, place_order: Callable[..., Order], uow: SqlAlchemyUnitOfWork, waits: Waits
) -> None:
    async with saga_harness() as saga:
        order = place_order()  # two lines: SKU-A x3 and SKU-B x2
        async with uow.begin() as transaction:
            await transaction.orders.save(order)  # writes order.placed.v1 to the outbox

        async def reserve_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "sent"

        await waits(reserve_sent, "the stock.reserve row for the placed order reaches sent")

        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        [recorded] = stand_in.requests_for(order.id.value)
        # `Order.rehydrate` re-sorts the lines by line id (a random UUID), so the request's line
        # order is deterministic per order but unrelated to product order: sorted by product code
        # before comparing (one request line per order line, with the right units)
        assert sorted(recorded.request["lines"], key=lambda line: line["productCode"]) == [
            {"productCode": "SKU-A", "units": 3},
            {"productCode": "SKU-B", "units": 2},
        ]
        assert recorded.request["orderReference"] == "ORD-000001"
        assert recorded.headers["x-correlation-id"] == str(order.id)
        assert await saga.db.status_of(order.id) == "placed", "R19 leaves the status unchanged"
        assert [row["command"] for row in await saga.db.command_rows(order.id)] == ["stock.reserve"]


async def test_the_bytes_a_responder_receives_are_the_committed_payload_text(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "sent"

        await waits(sent, "the stock.reserve row reaches sent")

        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert row is not None
        [recorded] = saga.stand_in(SagaCommandKind.STOCK_RESERVE).requests_for(order.id.value)
        assert recorded.body.decode("utf-8") == row["payload"], (
            "the responder received, byte for byte, the text that was committed"
        )
        parsed = from_wire_json(StockReserveRequestPayload, recorded.body)
        assert parsed.order_reference == "ORD-000101"
        assert sorted((line.product_code, line.units) for line in parsed.lines) == [
            ("SKU-A", 3),
            ("SKU-B", 2),
        ]
        assert recorded.body == to_wire_json(parsed).encode("utf-8"), "compact, the one serializer"


async def test_r20_moves_placed_to_stock_reserved_and_issues_credit_hold_for_the_order_total(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "stock.reserved.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def hold_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD)
            return row is not None and row["status"] == "sent"

        await waits(hold_sent, "the credit.hold row reaches sent")

        assert await saga.db.status_of(order.id) == "stock_reserved"
        [recorded] = saga.stand_in(SagaCommandKind.CREDIT_HOLD).requests_for(order.id.value)
        assert recorded.request["amount"] == {"amount": 8115, "currency": "EUR"}
        assert recorded.request["orderReference"] == "ORD-000101"
        assert type(recorded.request["amount"]["amount"]) is int


async def test_r21_moves_stock_reserved_through_credit_approved_to_confirmed_emits_exactly_one_order_confirmed_v1_and_issues_despatch_create(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        fact_id = await saga.publish_fact(
            "credit.approved.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def despatch_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.DESPATCH_CREATE)
            return row is not None and row["status"] == "sent"

        await waits(despatch_sent, "the despatch.create row reaches sent")

        assert await saga.db.status_of(order.id) == "confirmed"
        assert await saga.db.outbox_types(order.id) == ["order.confirmed.v1"], (
            "exactly one order.confirmed.v1, and no event for the intermediate credit_approved edge"
        )
        causation = await saga.db.fetchval(
            "SELECT causation_id FROM outbox WHERE aggregate_id = $1", order.id.value
        )
        assert causation == fact_id, "R12: the confirmation is caused by the credit.approved fact"
        [recorded] = saga.stand_in(SagaCommandKind.DESPATCH_CREATE).requests_for(order.id.value)
        assert recorded.request == {"orderReference": "ORD-000101"}


async def test_r22_moves_confirmed_to_despatched_and_issues_invoice_issue(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CONFIRMED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "order.despatched.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def invoice_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.INVOICE_ISSUE)
            return row is not None and row["status"] == "sent"

        await waits(invoice_sent, "the invoice.issue row reaches sent")

        assert await saga.db.status_of(order.id) == "despatched"
        [recorded] = saga.stand_in(SagaCommandKind.INVOICE_ISSUE).requests_for(order.id.value)
        assert sorted(recorded.request["lines"], key=lambda line: line["productCode"]) == [
            {"productCode": "SKU-A", "units": 3, "unitPrice": 1999},
            {"productCode": "SKU-B", "units": 2, "unitPrice": 1234},
        ]
        assert recorded.request["discount"] == 350
        assert recorded.request["currency"] == "EUR"


async def test_r23_moves_despatched_to_invoiced_and_issues_no_further_command_while_awaiting_a_remittance(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.DESPATCHED)
    async with saga_harness() as saga:
        invoiced = await saga.publish_fact(
            "invoice.issued.v1", correlation_id=order.id.value, reference="ORD-000101"
        )
        # A LATER, unrelated fact for the same order (same key, same partition): once ITS ignored
        # row exists, the consumer has moved past the invoice fact, so the absence below is
        # observed after the step, not before it.
        later = await saga.publish_fact(
            "credit.released.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def moved_on() -> bool:
            return bool(await saga.db.ignored(order.id, "credit.released.v1"))

        await waits(
            moved_on, "the later credit.released.v1 is consumed (ignored: the order is not paid)"
        )

        assert await saga.db.processed(invoiced)
        assert await saga.db.processed(later)
        assert await saga.db.status_of(order.id) == "invoiced"
        assert await saga.db.command_rows(order.id) == [], "R23: no further command is owed"
        assert all(not stand_in.requests for stand_in in saga.stand_ins.values())


async def test_r24_moves_invoiced_to_paid_then_paid_to_completed_and_emits_exactly_one_order_completed_v1(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.INVOICED)
    async with saga_harness() as saga:
        # back to back, the same key: one partition, in this order
        await saga.publish_fact(
            "payment.received.v1", correlation_id=order.id.value, reference="ORD-000101"
        )
        released = await saga.publish_fact(
            "credit.released.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def completed() -> bool:
            return "order.completed.v1" in await saga.db.outbox_types(order.id)

        await waits(completed, "an order.completed.v1 outbox row exists")

        assert await saga.db.status_of(order.id) == "completed"
        assert await saga.db.outbox_types(order.id) == ["order.completed.v1"], "exactly one"
        causation = await saga.db.fetchval(
            "SELECT causation_id FROM outbox WHERE aggregate_id = $1", order.id.value
        )
        assert causation == released
        assert await saga.db.command_rows(order.id) == []


async def test_saga_reaches_invoiced_then_completed_from_orders_create_against_stand_in_responders(
    saga_harness: Any,
    orders_host_factory: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    reference_data: Any,
    waits: Waits,
    nats_client: Any,
) -> None:
    await stand_in_stock_check(lambda _request: stock_reply([("SKU-A", 3, 50), ("SKU-B", 2, 50)]))
    async with saga_harness() as saga:
        for stand_in in saga.stand_ins.values():
            stand_in.emit = stand_in.kind is not SagaCommandKind.CREDIT_RELEASE
        body = json.dumps(
            {
                "retailerCode": "RET-01",
                "companyCode": "CMP-01",
                "currency": "EUR",
                "lines": [
                    {"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999},
                    {"productCode": "SKU-B", "quantity": 2, "unitPrice": 1234},
                ],
            }
        ).encode()

        reply = json.loads((await nats_client.request("orders.create", body, timeout=10)).data)
        assert reply["status"] == "placed", reply
        order_id = uuid.UUID(reply["orderId"])

        async def invoiced() -> bool:
            row = await saga.db.command_row(order_id, SagaCommandKind.INVOICE_ISSUE)
            return row is not None and row["status"] == "sent"

        await waits(invoiced, "the saga walked placed -> ... -> despatched and issued the invoice")
        assert [row["command"] for row in await saga.db.command_rows(order_id)] == [
            "stock.reserve",
            "credit.hold",
            "despatch.create",
            "invoice.issue",
        ]

        async def at_invoiced() -> bool:
            return bool(await saga.db.status_of(order_id) == "invoiced")

        await saga.publish_fact(
            "invoice.issued.v1", correlation_id=order_id, reference=reply["orderReference"]
        )
        await waits(at_invoiced, "invoice.issued.v1 moves the order to invoiced")
        await saga.publish_fact(
            "payment.received.v1", correlation_id=order_id, reference=reply["orderReference"]
        )
        await saga.publish_fact(
            "credit.released.v1", correlation_id=order_id, reference=reply["orderReference"]
        )

        async def completed() -> bool:
            return bool(await saga.db.status_of(order_id) == "completed")

        await waits(completed, "payment.received.v1 then credit.released.v1 complete the order")
        types = await saga.db.outbox_types(order_id)
        assert types.count("order.placed.v1") == 1
        assert types.count("order.confirmed.v1") == 1
        assert types.count("order.completed.v1") == 1
