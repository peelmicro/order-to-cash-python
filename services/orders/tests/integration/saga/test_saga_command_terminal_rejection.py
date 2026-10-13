# ruff: noqa: E501 - test names are the literal names the feature's acceptance items assign
"""Feature 42 end to end: a real NATS responder answering an `RpcError` to a saga command.

A terminal business code resolves the `saga_commands` row to `rejected` on the FIRST attempt, and the
running sweeper never touches it again; a transient code is retried exactly as feature 16 built it
(three in-line attempts, then `parked`). Every wait is on durable evidence: a row's status.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from io import StringIO
from types import ModuleType
from typing import Any

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.observability.logging import build_formatter

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


DISPATCHER_LOGGER = "otc_orders.saga.command_dispatcher"


@contextmanager
def rendered_dispatcher_lines() -> Iterator[StringIO]:
    """The dispatcher's own lines rendered by the PRODUCTION formatter (`correlationId` from the
    bound context, `traceId` from the active span), scoped to that one logger and removed after."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_formatter())
    logger = logging.getLogger(DISPATCHER_LOGGER)
    previous = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


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


async def test_or11_a_rejected_command_appends_no_saga_failed_publishes_no_dead_letter_and_logs_one_structured_error(
    saga_harness: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
) -> None:
    """`OR11` (gate G2, S7.3): a terminal `RpcError` ends the row in `rejected` with ONE structured
    ERROR line and nothing else: not the first-park hook, so no `order.saga_failed.v1`, no dead
    letter, `dead_lettered_at` NULL (`saga.md` 237-240: "not a saga failure"). The dead-letter
    absence is read from the broker by content, after a decoy for another order on the same
    private companion."""
    order = await order_at(OrderStatus.PLACED)
    servers = kafka_server.bootstrap_servers
    decoy_order = uuid.uuid4()
    decoy_id = uuid.uuid4()
    await dl_support.produce(
        servers,
        private_topics.dead_letter_of(private_topics.fulfillment),
        key=str(decoy_order).encode(),
        value=make_fact_bytes(
            "order.placed.v1",
            correlation_id=decoy_order,
            reference="ORD-000997",
            event_id=decoy_id,
        ),
    )
    with rendered_dispatcher_lines() as stream:
        async with saga_harness(topics=private_topics, OUTBOX_RELAY_ENABLED="false") as saga:
            saga.stand_in(SagaCommandKind.STOCK_RESERVE).behaviour = rpc_error("STOCK_UNAVAILABLE")
            await saga.publish_fact(
                "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
            )

            def error_lines() -> list[dict[str, Any]]:
                lines = [json.loads(line) for line in stream.getvalue().splitlines()]
                return [line for line in lines if line["level"] == "error"]

            async def logged() -> bool:
                return len(error_lines()) >= 1

            await waits(logged, "the rejected command's ERROR line is written")
            await asyncio.sleep(1.5)  # past the sweeper's cycles: nothing else may appear

            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            assert row is not None
            assert row["status"] == "rejected"
            assert row["dead_lettered_at"] is None, "OR11: a rejection is not a first park"
            assert row["triggering_event_envelope"] is not None, "the row did store its envelope"
            failed = await saga.db.fetch(
                "SELECT 1 FROM outbox WHERE aggregate_id = $1 AND event_type = 'order.saga_failed.v1'",
                order.id.value,
            )
            assert failed == [], "OR11: a rejected command appends no order.saga_failed.v1"

            seen = {
                topic: await dl_support.read_records(servers, topic)
                for topic in private_topics.dead_letters
            }
            assert any(
                record.event_id == str(decoy_id)
                for record in seen[private_topics.dead_letter_of(private_topics.fulfillment)]
            ), "the decoy is on the companion: the read is not vacuous"
            mentioning = {
                topic: [r.offset for r in records if str(order.id.value).encode() in r.value]
                for topic, records in seen.items()
            }
            assert all(not offsets for offsets in mentioning.values()), (
                f"OR11: a rejected command was dead-lettered: {mentioning}"
            )

            [line] = error_lines()
            lacking = {"correlationId", "command", "code", "traceId"} - line.keys()
            assert not lacking, f"OR11: the rejection's ERROR line lacks {sorted(lacking)}: {line}"
            assert line["event"] == "saga command rejected"
            assert line["logger"] == DISPATCHER_LOGGER
            assert line["correlationId"] == str(order.id.value)
            assert line["command"] == "stock.reserve"
            assert line["code"] == "STOCK_UNAVAILABLE"
            assert line["attempts"] == 1
            assert len(line["traceId"]) == 32, "the unit of work's trace is on the line"
            assert all(value not in ("", None) for value in line.values()), line
