"""R56 / R57 / OR4: the trace crosses the write model, the outbox and the broker (feature 27,
`design.md` 4.4; S3.5 and S3.8).

Real PostgreSQL, real Kafka, the PRODUCTION `OutboxWriter` (through the unit of work) and the
PRODUCTION `OutboxRelay` and `KafkaFactPublisher`. A header proves nothing on its own (a fresh span
produces one): every assertion extracts the header back and compares it with the REAL originating
span's ids (design 4.5). Spans come from providers the test builds (never registered globally) and
are read through the typed helper in `tests/observability/trace_support.py`. A record is SELECTED
by its own event id: the topic is shared by the session. Loop scope: the default (function).
"""

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.observability.telemetry import build_telemetry
from otc_orders.infrastructure.observability.trace_context import extract_kafka
from otc_orders.infrastructure.outbox.relay import OutboxRelay
from otc_orders.infrastructure.persistence.models import Outbox
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/trace_support.py"


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trace_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()


def header_values(headers: tuple[tuple[str, bytes], ...], name: str) -> list[bytes]:
    return [value for key, value in headers if key == name]


async def relay_once(
    relay: OutboxRelay,
) -> None:
    result = await relay.run_once()
    assert result.poisoned is None
    assert result.published >= 1, "the relay published nothing"


async def test_r56_the_relayed_record_carries_a_child_of_the_writers_span_through_the_producer_span(
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    clock: SystemClock,
    place_order: Any,
    kafka_publisher: Any,
    read_topic: Any,
) -> None:
    exporter, processor = support.new_recorder()
    telemetry = build_telemetry("orders", "", span_processors=[processor])
    order = place_order()
    (event_id,) = [e.event_id.value for e in order.domain_events]
    with telemetry.tracer.start_as_current_span("writer") as writer:
        writer_context = writer.get_span_context()
        async with uow.begin() as tx:
            await tx.orders.save(order)
    relay = OutboxRelay(
        sessions=sessions,
        publisher=kafka_publisher,
        clock=clock,
        batch_size=100,
        publish_timeout=5.0,
        tracer=telemetry.tracer,
    )

    await relay_once(relay)

    record = next(r for r in await read_topic() if r.event_id == event_id)
    values = header_values(record.headers, "traceparent")
    assert len(values) == 1, (
        "R56 hop outbox row -> Kafka record: the relayed record carries no traceparent (the relay "
        f"did not restore the row's trace_parent as the producer span's parent): {values}"
    )
    (raw,) = values
    carried = trace.get_current_span(extract_kafka(record.headers)).get_span_context()
    assert carried.trace_id == writer_context.trace_id, "the record continues the writer's trace"
    assert carried.span_id != writer_context.span_id, (
        "the record carries a NEW span, not the writer's"
    )
    published = [i for i in support.span_infos(exporter) if i.name == "outbox.publish"]
    assert len(published) == 1, (
        f"R56 hop relay -> producer span: {len(published)} 'outbox.publish' spans, expected 1"
    )
    assert published[0].span_id == carried.span_id, "the header names the PRODUCER span"
    assert published[0].parent_id == writer_context.span_id, (
        "the producer span is the writer's child"
    )
    assert published[0].kind == trace.SpanKind.PRODUCER
    assert raw.decode("ascii").split("-")[1] == support.trace_hex(writer_context.trace_id)
    telemetry.shutdown()


async def test_or4_a_row_written_with_no_span_is_published_with_no_traceparent_header_at_all(
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    clock: SystemClock,
    place_order: Any,
    kafka_publisher: Any,
    read_topic: Any,
) -> None:
    exporter, processor = support.new_recorder()
    telemetry = build_telemetry("orders", "", span_processors=[processor])
    order = place_order()
    (event_id,) = [e.event_id.value for e in order.domain_events]
    assert not trace.get_current_span().get_span_context().is_valid
    async with uow.begin() as tx:
        await tx.orders.save(order)
    async with sessions() as session:
        stored = await session.scalar(
            select(Outbox.trace_parent).where(Outbox.event_id == event_id)
        )
    assert stored is None, "the writer must not fabricate a trace for a write with no span"
    relay = OutboxRelay(
        sessions=sessions,
        publisher=kafka_publisher,
        clock=clock,
        batch_size=100,
        publish_timeout=5.0,
        tracer=telemetry.tracer,
    )

    await relay_once(relay)

    record = next(r for r in await read_topic() if r.event_id == event_id)
    assert header_values(record.headers, "traceparent") == []
    assert [name for name, _ in record.headers] == ["x-event-type", "content-type"]
    assert [i for i in support.span_infos(exporter) if i.name == "outbox.publish"] == []
    telemetry.shutdown()


async def test_r56_the_outbox_row_stores_the_writers_traceparent(
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
) -> None:
    telemetry = build_telemetry("orders", "")
    order = place_order()
    (event_id,) = [e.event_id.value for e in order.domain_events]
    with telemetry.tracer.start_as_current_span("writer") as writer:
        context = writer.get_span_context()
        async with uow.begin() as tx:
            await tx.orders.save(order)

    async with sessions() as session:
        stored = await session.scalar(
            select(Outbox.trace_parent).where(Outbox.event_id == event_id)
        )
    assert stored is not None
    assert stored.split("-")[1:3] == [
        support.trace_hex(context.trace_id),
        support.span_hex(context.span_id),
    ]
    telemetry.shutdown()


# ------------------------------------------------------------- S3.8: the whole chain, by parent id

REQUEST: dict[str, Any] = {
    "retailerCode": "RET-01",
    "companyCode": "CMP-01",
    "currency": "EUR",
    "lines": [{"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999, "lineDiscount": 250}],
}


async def wait_published(dsn: str, order_id: str) -> None:
    """Until the order's outbox row is stamped (the relay ran): paced, bounded, message names it."""
    import asyncio

    import asyncpg

    async with asyncio.timeout(30):
        while True:
            conn = await asyncpg.connect(dsn)
            try:
                published = await conn.fetchval(
                    "SELECT count(*) FROM outbox WHERE aggregate_id = $1::uuid"
                    " AND published_at IS NOT NULL",
                    order_id,
                )
            finally:
                await conn.close()
            if published:
                return
            await asyncio.sleep(0.1)


async def test_r56_one_orders_create_yields_server_span_then_transaction_span_then_producer_span_by_parent_id(  # noqa: E501
    traced_orders_factory: Any,
    stock_reply: Any,
    nats_server: Any,
    migrated_db: Any,
    read_topic: Any,
) -> None:
    import json

    import nats

    caller = support.caller_tracer()
    stock_headers: list[dict[str, str] | None] = []

    async def on_stock_check(message: Any) -> None:
        stock_headers.append(None if message.headers is None else dict(message.headers))
        await message.respond(stock_reply([("SKU-A", 3, 50)]))

    spy = await nats.connect(nats_server.url)
    try:
        await spy.subscribe("fulfillment.stock.check", cb=on_stock_check)
        await spy.flush()
        with caller.start_as_current_span("caller") as origin:
            origin_context = origin.get_span_context()
            sent = support.traceparent_header_of_current_span()
        async with traced_orders_factory() as host:
            reply = await host.client.request(
                "orders.create", json.dumps(REQUEST).encode(), timeout=10, headers=sent
            )
            body = json.loads(reply.data)
            assert body["status"] == "placed", body
            await wait_published(migrated_db.dsn, body["orderId"])
    finally:
        await spy.close()

    infos = support.span_infos(host.exporter)
    server = _hop(infos, "orders.create serve", "NATS request -> SERVER span")
    transaction = _hop(infos, "writemodel.transaction", "SERVER span -> write-model transaction")
    producer = _hop(infos, "outbox.publish", "outbox row -> relay producer span")
    stock_call = _hop(infos, "fulfillment.stock.check request", "SERVER span -> NATS CLIENT span")
    assert server.kind == trace.SpanKind.SERVER
    assert (server.trace_id, server.parent_id) == (origin_context.trace_id, origin_context.span_id)
    assert (transaction.trace_id, transaction.parent_id) == (server.trace_id, server.span_id)
    assert (producer.trace_id, producer.parent_id) == (server.trace_id, transaction.span_id)
    assert (stock_call.trace_id, stock_call.parent_id) == (server.trace_id, server.span_id)
    assert stock_call.kind == trace.SpanKind.CLIENT
    assert {i.service for i in (server, transaction, producer, stock_call)} == {"orders"}
    # the stand-in Fulfillment received the CLIENT span's context
    (received,) = stock_headers
    assert received is not None, (
        "R56 hop NATS CLIENT span -> Fulfillment: the request had no headers"
    )
    assert "traceparent" in received, (
        f"R56 hop NATS CLIENT span -> Fulfillment: no traceparent header, got {sorted(received)}"
    )
    stock_context = trace.get_current_span(
        extract_kafka([("traceparent", received["traceparent"].encode("ascii"))])
    ).get_span_context()
    assert (stock_context.trace_id, stock_context.span_id) == (server.trace_id, stock_call.span_id)
    # and the record on the broker carries the PRODUCER span
    order_id = uuid.UUID(body["orderId"])
    records = [r for r in await read_topic() if r.key is not None and _aggregate_of(r) == order_id]
    (record,) = records
    carried = trace.get_current_span(extract_kafka(record.headers)).get_span_context()
    assert (carried.trace_id, carried.span_id) == (server.trace_id, producer.span_id)


def _hop(infos: Any, name: str, hop: str) -> Any:
    """The one span named `name`; its absence names the HOP that did not trace (R56)."""
    found = support.by_name(infos, name)
    assert len(found) == 1, f"R56 hop {hop}: {len(found)} spans named {name!r}, expected exactly 1"
    return found[0]


def _aggregate_of(record: Any) -> uuid.UUID | None:
    import json

    try:
        return uuid.UUID(json.loads(record.value)["aggregateId"])
    except ValueError, KeyError, TypeError:
        return None
