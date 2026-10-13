"""R56 / R57: the saga's command carries the trace of the fact that owed it (feature 27
`design.md` 4.4; S3.10, orchestrator task 6.5).

The REAL runtime (the saga harness's lifespan, whose `start_runtime` this test wraps ONLY to hand an
in-memory span processor to the runtime's own provider), a REAL Kafka fact published with a known
`traceparent` header, and a stand-in Fulfillment on the real `fulfillment.stock.reserve` subject
that records the headers it receives. The fast path's dispatch task is created by the code that
handles the fact, so it inherits the consuming context; a dispatch task started in an empty context
would send the command under a trace of its own.
"""

import importlib.util
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import otc_orders.main
from otc_contracts import to_wire_json
from otc_contracts.generated.asyncapi import Line3, StockReserveRequestPayload
from otc_orders.application.ports.saga_command_store import OwedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.composition import OrdersSettings, start_runtime
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.observability.trace_context import extract_nats
from otc_shared_kernel import UniqueId

SUPPORT_PATH = Path(__file__).resolve().parents[5] / "tests/observability/trace_support.py"

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trace_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()


def ancestors_of(infos: list[Any], start: Any) -> list[Any]:
    """The chain of spans above `start`, nearest first, following parent ids within `infos`."""
    by_id = {info.span_id: info for info in infos}
    chain: list[Any] = []
    parent = start.parent_id
    while parent is not None and parent in by_id:
        chain.append(by_id[parent])
        parent = by_id[parent].parent_id
    return chain


async def test_the_fast_path_dispatch_continues_the_facts_trace(
    saga_harness: Any, order_at: OrderAt, waits: Waits, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = InMemorySpanExporter()
    real_start_runtime = start_runtime

    async def start_with_recorder(settings: OrdersSettings) -> Any:
        return await real_start_runtime(settings, span_processors=[SimpleSpanProcessor(exporter)])

    monkeypatch.setattr(otc_orders.main, "start_runtime", start_with_recorder)
    order = await order_at(OrderStatus.PLACED)
    with support.caller_tracer().start_as_current_span("fact producer") as origin:
        producer = origin.get_span_context()
        inbound = support.traceparent_header_of_current_span()

    async with saga_harness() as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        await saga.publish_fact(
            "order.placed.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
            headers=[("traceparent", inbound["traceparent"].encode("ascii"))],
        )

        async def received() -> bool:
            return bool(stand_in.requests_for(order.id.value))

        await waits(received, "the stand-in Fulfillment receives the fast path's stock.reserve")
        (recorded,) = stand_in.requests_for(order.id.value)

    infos = support.span_infos(exporter)
    consumers = [i for i in infos if i.kind == trace.SpanKind.CONSUMER]
    (consumer,) = consumers
    assert (consumer.trace_id, consumer.parent_id) == (producer.trace_id, producer.span_id)
    (client,) = support.by_name(infos, "fulfillment.stock.reserve request")
    assert client.kind == trace.SpanKind.CLIENT
    assert client.trace_id == producer.trace_id, "the command left under the fact's trace"
    assert consumer.span_id in [a.span_id for a in ancestors_of(infos, client)], (
        "the command's CLIENT span descends from the consume span of the fact that owed it"
    )
    received_context = trace.get_current_span(
        extract_nats({"traceparent": recorded.headers["traceparent"]})
    ).get_span_context()
    assert (received_context.trace_id, received_context.span_id) == (
        producer.trace_id,
        client.span_id,
    )


async def owe_stock_reserve(uow: Any, order: Order) -> None:
    """Commit a `pending` stock.reserve row for `order` through the real unit of work and publish
    NOTHING: no fast-path signal exists, so only a sweeper cycle can issue it."""
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


async def test_or10_a_swept_command_continues_the_trace_recorded_at_enqueue(
    saga_harness: Any, order_at: OrderAt, waits: Waits, uow: Any
) -> None:
    exporter, processor = support.new_recorder()
    order = await order_at(OrderStatus.PLACED)
    with support.caller_tracer().start_as_current_span("enqueuer") as origin:
        recorded = origin.get_span_context()
        await owe_stock_reserve(uow, order)  # the row records the CURRENT span's traceparent

    async with saga_harness(span_processors=[processor]) as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)

        async def received() -> bool:
            return bool(stand_in.requests_for(order.id.value))

        await waits(received, "the sweeper issues the owed stock.reserve to the stand-in")
        (arrived,) = stand_in.requests_for(order.id.value)

    infos = support.span_infos(exporter)
    (dispatch,) = support.by_name(infos, "saga.command.dispatch")
    assert dispatch.kind == trace.SpanKind.INTERNAL
    assert (dispatch.trace_id, dispatch.parent_id) == (recorded.trace_id, recorded.span_id), (
        "the dispatch span continues the trace recorded at enqueue"
    )
    (client,) = support.by_name(infos, "fulfillment.stock.reserve request")
    assert client.parent_id == dispatch.span_id
    sent = trace.get_current_span(
        extract_nats({"traceparent": arrived.headers["traceparent"]})
    ).get_span_context()
    assert (sent.trace_id, sent.span_id) == (recorded.trace_id, client.span_id), (
        "the command left under the trace recorded at enqueue"
    )


async def test_or10_a_row_with_no_recorded_trace_starts_a_fresh_root(
    saga_harness: Any, order_at: OrderAt, waits: Waits, uow: Any
) -> None:
    exporter, processor = support.new_recorder()
    order = await order_at(OrderStatus.PLACED)
    await owe_stock_reserve(uow, order)  # no span is active: the row records no trace

    async with saga_harness(span_processors=[processor]) as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)

        async def received() -> bool:
            return bool(stand_in.requests_for(order.id.value))

        await waits(received, "the sweeper issues the owed stock.reserve to the stand-in")
        (arrived,) = stand_in.requests_for(order.id.value)
        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert row is not None
        assert row["trace_parent"] is None, "nothing was recorded at enqueue"

    infos = support.span_infos(exporter)
    (dispatch,) = support.by_name(infos, "saga.command.dispatch")
    assert dispatch.parent_id is None, "a root span: no parent was fabricated from the row"
    (client,) = support.by_name(infos, "fulfillment.stock.reserve request")
    assert (client.trace_id, client.parent_id) == (dispatch.trace_id, dispatch.span_id)
    sent = trace.get_current_span(
        extract_nats({"traceparent": arrived.headers["traceparent"]})
    ).get_span_context()
    assert (sent.trace_id, sent.span_id) == (dispatch.trace_id, client.span_id)
