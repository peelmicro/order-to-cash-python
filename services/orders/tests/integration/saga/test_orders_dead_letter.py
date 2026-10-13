# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R16` for the Orders saga consumer, end to end (S4.17, S4.24): a poison fact is retried, then
dead-lettered byte for byte, and the offset the BROKER holds moves past it.

Every topic is private to the test (item 10): the poison is never on a topic another test reads.
The dead letters are read from the broker BY CONTENT (the poison's `eventId`) after a decoy was
published first on the same `.dlq`; the committed offsets are the group's as the broker reports
them, never inferred. The poison is a well-formed envelope whose payload fails its model, so the
failure is the handler's own and happens on every attempt.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otc_contracts import FACT_MODELS, Envelope, from_wire_json, to_wire_json
from otc_orders.application.saga import fact_command_handlers
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]

GROUP = "orders.saga"
FAST = {
    "FACT_RETRY_BACKOFF_MS": "20",
    "OUTBOX_RELAY_ENABLED": "false",
    "SAGA_SWEEPER_ENABLED": "false",
}
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def poison_bytes(make_fact_bytes: Callable[..., bytes], order: Order, event_id: uuid.UUID) -> bytes:
    """A well-formed envelope (it passes `Envelope[dict]`) whose PAYLOAD fails `order.placed.v1`'s
    model, written the way no serializer would: keys reversed, spaces in the separators, a
    top-level field the model does not declare, non-ASCII text."""
    document = json.loads(
        make_fact_bytes(
            "order.placed.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
            event_id=event_id,
            payload={"orderReference": 42, "note": "ñandú 日本"},
        )
    )
    document["zzUndeclared"] = True
    return json.dumps(
        dict(reversed(list(document.items()))), separators=(", ", ": "), ensure_ascii=False
    ).encode("utf-8")


def expected_error(produced: bytes) -> str:
    """What the handler's validation says about `produced`, computed here by running the same
    validation on the same bytes (not by quoting the production code's string)."""
    envelope = from_wire_json(Envelope[dict[str, Any]], produced)
    try:
        from_wire_json(FACT_MODELS[envelope.event_type], to_wire_json(envelope))
    except ValueError as error:
        return f"{type(error).__name__}: {error}"[:1000]
    raise AssertionError("the poison validated: it is not a poison")


class Attempts:
    """Counts the handler's validations of ONE event id (the attempts the wrapper made)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, event_id: uuid.UUID) -> None:
        self.count = 0
        original = fact_command_handlers.build_saga_fact

        def counting(command: Any) -> Any:
            if command.envelope.event_id == event_id:
                self.count += 1
            return original(command)

        monkeypatch.setattr(fact_command_handlers, "build_saga_fact", counting)


async def letters_of(
    dl_support: ModuleType, servers: str, topic: str, event_id: uuid.UUID
) -> list[Any]:
    return [
        record
        for record in await dl_support.read_records(servers, topic)
        if record.event_id == str(event_id)
    ]


async def test_r16_a_poison_fact_is_retried_then_dead_lettered_byte_for_byte_with_every_header_and_the_committed_offset_read_from_the_broker_moves_past_it(
    saga_harness: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    event_id, decoy_id = uuid.uuid4(), uuid.uuid4()
    produced = poison_bytes(make_fact_bytes, order, event_id)
    source, servers = private_topics.orders, kafka_server.bootstrap_servers
    letters = private_topics.dead_letter_of(source)
    attempts = Attempts(monkeypatch, event_id)
    await dl_support.produce(
        servers,
        letters,
        key=b"decoy",
        value=make_fact_bytes(
            "order.placed.v1",
            correlation_id=uuid.uuid4(),
            reference="ORD-000999",
            event_id=decoy_id,
        ),
    )
    async with saga_harness(topics=private_topics, **FAST) as saga:
        before = datetime.now(UTC)
        partition, offset = await dl_support.produce(
            servers, source, key=str(order.id.value).encode(), value=produced
        )

        async def dead_lettered() -> bool:
            return len(await letters_of(dl_support, servers, letters, event_id)) == 1

        await waits(dead_lettered, "the poison's dead letter is on the private .dlq")

        async def committed_past() -> bool:
            offsets = await dl_support.committed_offsets_of(servers, GROUP, private_topics.all)
            return bool(offsets.get((source, partition)) == offset + 1)

        await waits(
            committed_past, "the group's committed offset (read from the broker) is poison + 1"
        )

        [letter] = await letters_of(dl_support, servers, letters, event_id)
        assert attempts.count == 3, "the wrapper attempted the processing exactly three times"
        assert letter.value == produced, "the ORIGINAL bytes, not a re-serialisation"
        assert letter.key == str(order.id.value).encode(), "keyed by the original record key"
        headers = letter.headers
        assert headers["x-failed-consumer"] == b"orders.saga"
        assert headers["x-attempts"] == b"3"
        assert headers["x-error"].decode() == expected_error(produced)
        assert headers["x-original-topic"] == source.encode()
        assert headers["x-event-type"] == b"order.placed.v1"
        assert headers["content-type"] == b"application/json"
        first, final = headers["x-first-failed-at"].decode(), headers["x-failed-at"].decode()
        assert INSTANT.match(first), first
        assert INSTANT.match(final), final
        assert first < final, "20 ms and 40 ms of back-off separate the first failure from the last"
        assert datetime.fromisoformat(first.replace("Z", "+00:00")) >= before - timedelta(
            milliseconds=1
        ), "the first failure happened after the test published the poison"

        # the partition moves on: a next, valid fact with the SAME key is processed and committed
        next_id = await saga.publish_fact(
            "order.placed.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        next_partition, next_offset = saga.positions[next_id][1:]

        async def next_processed() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            offsets = await dl_support.committed_offsets_of(servers, GROUP, private_topics.all)
            return bool(
                row is not None and offsets.get((source, next_partition)) == next_offset + 1
            )

        await waits(next_processed, "the next fact of the same key is processed and committed")
        assert next_partition == partition, "the same key lands on the same partition"
        assert next_offset > offset
        assert len(await letters_of(dl_support, servers, letters, event_id)) == 1


async def test_r57_the_consume_span_continues_the_inbound_trace_and_the_dead_letter_carries_it(
    saga_harness: Any,
    private_topics: Any,
    dl_support: ModuleType,
    trace_support: ModuleType,
    kafka_server: Any,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    event_id = uuid.uuid4()
    produced = poison_bytes(make_fact_bytes, order, event_id)
    source, servers = private_topics.orders, kafka_server.bootstrap_servers
    letters = private_topics.dead_letter_of(source)
    exporter = InMemorySpanExporter()
    with trace_support.caller_tracer().start_as_current_span("fact producer") as origin:
        inbound_context = origin.get_span_context()
        inbound = trace_support.traceparent_header_of_current_span()["traceparent"]

    async with saga_harness(
        topics=private_topics, span_processors=[SimpleSpanProcessor(exporter)], **FAST
    ):
        await dl_support.produce(
            servers,
            source,
            key=str(order.id.value).encode(),
            value=produced,
            headers=[("traceparent", inbound.encode("ascii"))],
        )

        async def dead_lettered() -> bool:
            return len(await letters_of(dl_support, servers, letters, event_id)) == 1

        await waits(dead_lettered, "the poison's dead letter is on the private .dlq")
        [letter] = await letters_of(dl_support, servers, letters, event_id)

    consumers = [
        info
        for info in trace_support.span_infos(exporter)
        if info.kind == trace.SpanKind.CONSUMER and info.name == f"{source} process"
    ]
    (consumer,) = consumers
    assert (consumer.trace_id, consumer.parent_id) == (
        inbound_context.trace_id,
        inbound_context.span_id,
    ), "the consume span continues the inbound trace (it is not a fresh root)"
    carried = letter.headers["traceparent"].decode()
    _, trace_hex, span_hex, _ = carried.split("-")
    assert trace_hex == trace_support.trace_hex(inbound_context.trace_id), "the same trace"
    assert span_hex == trace_support.span_hex(consumer.span_id), (
        "the dead letter was made under the consume span"
    )


class Refusing:
    """A dead-letter producer whose broker never acknowledges."""

    def __init__(self, refused: list[str], **options: Any) -> None:
        self._refused = refused

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_and_wait(self, topic: str, **record: Any) -> None:
        self._refused.append(topic)
        raise ConnectionError("the dead-letter broker did not acknowledge")


async def test_or8_an_unacknowledged_dead_letter_leaves_the_offset_uncommitted_and_a_restarted_consumer_redelivers(
    saga_harness: Any,
    private_topics: Any,
    broker: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    event_id = uuid.uuid4()
    produced = poison_bytes(make_fact_bytes, order, event_id)
    source, servers = private_topics.orders, kafka_server.bootstrap_servers
    letters = private_topics.dead_letter_of(source)
    refused: list[str] = []

    try:
        async with saga_harness(
            cleanup=False,
            topics=private_topics,
            dead_letter_producer_factory=lambda **options: Refusing(refused, **options),
            **FAST,
        ) as first:
            # a valid fact of the SAME key is processed and committed first, so the committed
            # offset is a real position and the poison is the very next offset of its partition
            baseline_id = await first.publish_fact(
                "order.placed.v1",
                correlation_id=order.id.value,
                reference=order.order_reference.value,
            )
            partition, baseline_offset = first.positions[baseline_id][1:]

            async def baseline_committed() -> bool:
                offsets = await dl_support.committed_offsets_of(servers, GROUP, private_topics.all)
                return bool(offsets.get((source, partition)) == baseline_offset + 1)

            await waits(baseline_committed, "the baseline fact is committed")
            _, offset = await dl_support.produce(
                servers, source, key=str(order.id.value).encode(), value=produced
            )
            assert offset == baseline_offset + 1

            async def refused_twice() -> bool:
                return len(refused) >= 2

            await waits(
                refused_twice,
                "the publication was refused twice: the record was DELIVERED AGAIN after the first refusal",
            )
            offsets = await dl_support.committed_offsets_of(servers, GROUP, private_topics.all)
            assert offsets.get((source, partition)) == baseline_offset + 1, (
                "the committed offset (read from the broker) is unchanged: the poison is not committed"
            )
            assert await letters_of(dl_support, servers, letters, event_id) == [], (
                "nothing reached the .dlq"
            )

        async with saga_harness(history="keep", topics=private_topics, **FAST):

            async def dead_lettered_and_committed() -> bool:
                offsets = await dl_support.committed_offsets_of(servers, GROUP, private_topics.all)
                return bool(
                    len(await letters_of(dl_support, servers, letters, event_id)) == 1
                    and offsets.get((source, partition)) == offset + 1
                )

            await waits(
                dead_lettered_and_committed,
                "the restarted consumer redelivers the record: one dead letter, committed offset poison + 1",
            )
    finally:
        await broker.delete_group()


async def test_f1_a_stop_during_a_long_backoff_returns_within_a_small_bound_with_the_offset_unchanged_and_nothing_on_the_dlq_and_the_record_is_redelivered_after_the_restart(
    saga_harness: Any,
    private_topics: Any,
    broker: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
    caplog: pytest.LogCaptureFixture,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    event_id = uuid.uuid4()
    produced = poison_bytes(make_fact_bytes, order, event_id)
    source, servers = private_topics.orders, kafka_server.bootstrap_servers
    letters = private_topics.dead_letter_of(source)
    decoy_id = uuid.uuid4()
    await dl_support.produce(
        servers,
        letters,
        key=b"decoy",
        value=make_fact_bytes(
            "order.placed.v1",
            correlation_id=uuid.uuid4(),
            reference="ORD-000999",
            event_id=decoy_id,
        ),
    )
    stopped_in: float | None = None
    loop = asyncio.get_running_loop()

    try:
        with caplog.at_level(logging.INFO):
            async with saga_harness(
                cleanup=False,
                topics=private_topics,
                **(FAST | {"FACT_RETRY_BACKOFF_MS": "30000"}),
            ) as first:
                baseline_id = await first.publish_fact(
                    "order.placed.v1",
                    correlation_id=order.id.value,
                    reference=order.order_reference.value,
                )
                partition, baseline_offset = first.positions[baseline_id][1:]

                async def baseline_committed() -> bool:
                    offsets = await dl_support.committed_offsets_of(
                        servers, GROUP, private_topics.all
                    )
                    return bool(offsets.get((source, partition)) == baseline_offset + 1)

                await waits(baseline_committed, "the baseline fact is committed")
                _, offset = await dl_support.produce(
                    servers, source, key=str(order.id.value).encode(), value=produced
                )

                async def first_attempt_failed() -> bool:
                    return any(
                        record.getMessage() == "fact processing attempt failed"
                        for record in caplog.records
                    )

                await waits(
                    first_attempt_failed, "the first attempt failed: the 30 s back-off began"
                )
                await asyncio.sleep(
                    0.3
                )  # the sleep call follows the log line within the same task step
                stop_began = loop.monotonic() if hasattr(loop, "monotonic") else loop.time()
            stopped_in = (
                loop.monotonic() if hasattr(loop, "monotonic") else loop.time()
            ) - stop_began

        assert stopped_in is not None
        assert stopped_in < 10, (
            f"the stop signal did not end the 30 s back-off: stopping took {stopped_in:.1f} s"
        )
        offsets = await dl_support.committed_offsets_of(servers, GROUP, private_topics.all)
        assert offsets.get((source, partition)) == baseline_offset + 1, (
            "the committed offset (read from the broker) is unchanged by the stop"
        )
        assert await letters_of(dl_support, servers, letters, event_id) == [], (
            "the interrupted record was not dead-lettered"
        )
        lines = [record.getMessage() for record in caplog.records]
        assert not any(line.startswith("fact handler failed") for line in lines), (
            "a stop is not a handler failure"
        )
        assert any(line.startswith("fact retry interrupted by shutdown") for line in lines)

        # redelivered after the restart: a fresh round of attempts ends in its dead letter
        async with saga_harness(history="keep", topics=private_topics, **FAST):

            async def dead_lettered_and_committed() -> bool:
                current = await dl_support.committed_offsets_of(servers, GROUP, private_topics.all)
                return bool(
                    len(await letters_of(dl_support, servers, letters, event_id)) == 1
                    and current.get((source, partition)) == offset + 1
                )

            await waits(
                dead_lettered_and_committed,
                "after the restart the record is redelivered, dead-lettered once and committed",
            )
    finally:
        await broker.delete_group()
