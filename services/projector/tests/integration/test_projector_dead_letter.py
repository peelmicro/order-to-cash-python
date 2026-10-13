# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R16` for the Projector, through the REAL lifespan (S4.18, S4.22, S4.24).

A poison is a registered type (`order.placed.v1`) whose payload fails its model: `parse_fact`
raises inside the wrapped callable on every attempt. Every topic is private to the test
(`Topics`: three sources and their three `.dlq` companions); the dead letters are read from the
broker by content after a decoy; the committed offsets are the group's as the broker reports them.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otc_contracts import parse_fact
from otc_projector.composition import Externals
from otc_projector.presentation import projector_facts_consumer

pytestmark = pytest.mark.integration

INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


async def until(
    claim: str, condition: Callable[[], Awaitable[bool]], seconds: float = 30.0
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not await condition():
        if loop.time() > deadline:
            pytest.fail(f"{claim}: not observed within {seconds} s")
        await asyncio.sleep(0.1)


def poison_bytes(facts: Any, order: uuid.UUID, event_id: uuid.UUID, reference: str) -> bytes:
    """A well-formed envelope whose payload fails `order.placed.v1`'s model, written the way no
    serializer would: keys reversed, spaces in the separators, an undeclared top-level field,
    non-ASCII text."""
    document = json.loads(
        facts.wire(
            facts.build(
                "order.placed.v1",
                correlation_id=order,
                event_id=event_id,
                payload={"order_reference": reference},
            )
        )
    )
    document["payload"]["orderReference"] = 42  # an int where the model wants "ORD-nnnnnn"
    document["payload"]["note"] = "ñandú 日本"
    document["zzUndeclared"] = True
    return json.dumps(
        dict(reversed(list(document.items()))), separators=(", ", ": "), ensure_ascii=False
    ).encode("utf-8")


def expected_error(produced: bytes) -> str:
    """What the validation says about `produced`, computed here by running it on the same bytes."""
    try:
        parse_fact(produced)
    except ValueError as error:
        return f"{type(error).__name__}: {error}"[:1000]
    raise AssertionError("the poison validated: it is not a poison")


class Attempts:
    """Counts the parses of ONE event id (the attempts the wrapper made)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, event_id: uuid.UUID) -> None:
        self.count = 0
        original = parse_fact

        def counting(data: str | bytes) -> Any:
            if json.loads(data).get("eventId") == str(event_id):
                self.count += 1
            return original(data)

        monkeypatch.setattr(projector_facts_consumer, "parse_fact", counting)


class Refusing:
    """A dead-letter producer whose broker never acknowledges."""

    def __init__(self) -> None:
        self.refused = 0

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish(self, letter: Any) -> None:
        self.refused += 1
        raise ConnectionError("the dead-letter broker did not acknowledge")


async def letters_of(dl_support: Any, servers: str, topic: str, event_id: uuid.UUID) -> list[Any]:
    return [
        record
        for record in await dl_support.read_records(servers, topic)
        if record.event_id == str(event_id)
    ]


async def committed(
    dl_support: Any, env: Any, group: str, topic: str, partition: int
) -> int | None:
    offsets = await dl_support.committed_offsets_of(env.kafka, group, env.topics.all)
    found: int | None = offsets.get((topic, partition))
    return found


async def test_r16_a_poison_fact_is_retried_then_dead_lettered_byte_for_byte_with_every_header_and_the_committed_offset_read_from_the_broker_moves_past_it(
    runtime_env: Any,
    dl_support: Any,
    facts: Any,
    new_reference: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = runtime_env
    order, event_id = uuid.uuid4(), uuid.uuid4()
    source = env.topics.orders
    letters = env.topics.dead_letter_of(source)
    produced = poison_bytes(facts, order, event_id, new_reference())
    attempts = Attempts(monkeypatch, event_id)
    await dl_support.produce(
        env.kafka,
        letters,
        key=b"decoy",
        value=facts.wire(
            facts.build("order.placed.v1", payload={"order_reference": new_reference()})
        ),
    )
    group = f"pdl-a-{uuid.uuid4().hex[:8]}"
    runtime = await env.start(group)
    try:
        before = datetime.now(UTC)
        partition, offset = await dl_support.produce(
            env.kafka, source, key=str(order).encode(), value=produced
        )

        async def dead_lettered() -> bool:
            return len(await letters_of(dl_support, env.kafka, letters, event_id)) == 1

        await until("the poison's dead letter is on the private .dlq", dead_lettered)

        async def committed_past() -> bool:
            return bool(await committed(dl_support, env, group, source, partition) == offset + 1)

        await until(
            "the group's committed offset (read from the broker) is poison + 1", committed_past
        )

        [letter] = await letters_of(dl_support, env.kafka, letters, event_id)
        assert attempts.count == 3, "the wrapper attempted the processing exactly three times"
        assert letter.value == produced, "the ORIGINAL bytes, not a re-serialisation"
        assert letter.key == str(order).encode(), "keyed by the original record key"
        headers = letter.headers
        assert headers["x-failed-consumer"] == b"projector"
        assert headers["x-attempts"] == b"3"
        assert headers["x-error"].decode() == expected_error(produced)
        assert headers["x-original-topic"] == source.encode()
        assert headers["x-event-type"] == b"order.placed.v1"
        assert headers["content-type"] == b"application/json"
        first, final = headers["x-first-failed-at"].decode(), headers["x-failed-at"].decode()
        assert INSTANT.match(first), first
        assert INSTANT.match(final), final
        assert first < final, "10 ms and 20 ms of back-off separate the first failure from the last"
        assert datetime.fromisoformat(first.replace("Z", "+00:00")) >= before - timedelta(
            milliseconds=1
        )

        # the partition moves on: a next, valid fact with the SAME key is projected and committed
        next_event = facts.build(
            "order.placed.v1", correlation_id=order, payload={"order_reference": new_reference()}
        )
        next_partition, next_offset = await dl_support.produce(
            env.kafka, source, key=str(order).encode(), value=facts.wire(next_event)
        )
        assert next_partition == partition

        model = env.read_model()
        try:

            async def projected() -> bool:
                found = await model.collection.find_one({"_id": str(order)})
                at_end = (
                    await committed(dl_support, env, group, source, partition) == next_offset + 1
                )
                return found is not None and at_end

            await until("the next fact of the same key is projected and committed", projected)
        finally:
            await model.client.close()
        assert len(await letters_of(dl_support, env.kafka, letters, event_id)) == 1
    finally:
        await runtime.stop()


async def test_r57_the_consume_span_continues_the_inbound_trace_and_the_dead_letter_carries_it(
    runtime_env: Any, dl_support: Any, trace_support: Any, facts: Any, new_reference: Any
) -> None:
    env = runtime_env
    order, event_id = uuid.uuid4(), uuid.uuid4()
    source = env.topics.orders
    letters = env.topics.dead_letter_of(source)
    produced = poison_bytes(facts, order, event_id, new_reference())
    exporter = InMemorySpanExporter()
    with trace_support.caller_tracer().start_as_current_span("fact producer") as origin:
        inbound_context = origin.get_span_context()
        inbound = trace_support.traceparent_header_of_current_span()["traceparent"]
    runtime = await env.start(
        f"pdl-b-{uuid.uuid4().hex[:8]}", span_processors=[SimpleSpanProcessor(exporter)]
    )
    try:
        await dl_support.produce(
            env.kafka,
            source,
            key=str(order).encode(),
            value=produced,
            headers=[("traceparent", inbound.encode("ascii"))],
        )

        async def dead_lettered() -> bool:
            return len(await letters_of(dl_support, env.kafka, letters, event_id)) == 1

        await until("the poison's dead letter is on the private .dlq", dead_lettered)
        [letter] = await letters_of(dl_support, env.kafka, letters, event_id)
    finally:
        await runtime.stop()

    (consumer,) = [
        info
        for info in trace_support.span_infos(exporter)
        if info.kind == trace.SpanKind.CONSUMER and info.name == f"{source} process"
    ]
    assert (consumer.trace_id, consumer.parent_id) == (
        inbound_context.trace_id,
        inbound_context.span_id,
    ), "the consume span continues the inbound trace (it is not a fresh root)"
    _, trace_hex, span_hex, _ = letter.headers["traceparent"].decode().split("-")
    assert trace_hex == trace_support.trace_hex(inbound_context.trace_id), "the same trace"
    assert span_hex == trace_support.span_hex(consumer.span_id), (
        "the dead letter was made under the consume span"
    )


async def test_or8_an_unacknowledged_dead_letter_leaves_the_offset_uncommitted_and_a_restarted_consumer_redelivers(
    runtime_env: Any, dl_support: Any, facts: Any, new_reference: Any
) -> None:
    """Item 11's production-path companion: the Projector's `I4-commit-before-handler` arm run on
    the real lifespan. Lifespan 1 cannot dead-letter; lifespan 2 can and is the SAME group."""
    env = runtime_env
    order, event_id = uuid.uuid4(), uuid.uuid4()
    source = env.topics.orders
    letters = env.topics.dead_letter_of(source)
    group = f"pdl-c-{uuid.uuid4().hex[:8]}"
    refusing = Refusing()
    first = await env.start(group, externals=Externals(dead_letters=lambda settings: refusing))
    try:
        baseline = facts.build(
            "order.placed.v1", correlation_id=order, payload={"order_reference": new_reference()}
        )
        partition, baseline_offset = await dl_support.produce(
            env.kafka, source, key=str(order).encode(), value=facts.wire(baseline)
        )

        async def baseline_committed() -> bool:
            return bool(
                await committed(dl_support, env, group, source, partition) == baseline_offset + 1
            )

        await until("the baseline fact is committed", baseline_committed)
        _, offset = await dl_support.produce(
            env.kafka,
            source,
            key=str(order).encode(),
            value=poison_bytes(facts, order, event_id, new_reference()),
        )
        assert offset == baseline_offset + 1

        async def refused_twice() -> bool:
            return refusing.refused >= 2

        await until(
            "the publication was refused twice: the record was DELIVERED AGAIN after the first refusal",
            refused_twice,
            seconds=60,
        )
        assert await committed(dl_support, env, group, source, partition) == baseline_offset + 1, (
            "the committed offset (read from the broker) is unchanged: the poison is not committed"
        )
        assert await letters_of(dl_support, env.kafka, letters, event_id) == []
    finally:
        await first.stop()

    second = await env.start(group)
    try:

        async def dead_lettered_and_committed() -> bool:
            return bool(
                len(await letters_of(dl_support, env.kafka, letters, event_id)) == 1
                and await committed(dl_support, env, group, source, partition) == offset + 1
            )

        await until(
            "the restarted consumer redelivers the record: one dead letter, committed offset poison + 1",
            dead_lettered_and_committed,
            seconds=60,
        )
    finally:
        await second.stop()


async def test_f1_a_stop_during_a_long_backoff_returns_within_a_small_bound_with_the_offset_unchanged_and_nothing_on_the_dlq_and_the_record_is_redelivered_after_the_restart(
    runtime_env: Any,
    dl_support: Any,
    facts: Any,
    new_reference: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = runtime_env
    order, event_id = uuid.uuid4(), uuid.uuid4()
    source = env.topics.orders
    letters = env.topics.dead_letter_of(source)
    group = f"pdl-f1-{uuid.uuid4().hex[:8]}"
    loop = asyncio.get_running_loop()

    with caplog.at_level(logging.INFO):
        runtime = await env.start(group, backoff_ms=30_000)
        baseline = facts.build(
            "order.placed.v1", correlation_id=order, payload={"order_reference": new_reference()}
        )
        partition, baseline_offset = await dl_support.produce(
            env.kafka, source, key=str(order).encode(), value=facts.wire(baseline)
        )

        async def baseline_committed() -> bool:
            return bool(
                await committed(dl_support, env, group, source, partition) == baseline_offset + 1
            )

        await until("the baseline fact is committed", baseline_committed)
        _, offset = await dl_support.produce(
            env.kafka,
            source,
            key=str(order).encode(),
            value=poison_bytes(facts, order, event_id, new_reference()),
        )

        async def first_attempt_failed() -> bool:
            return any(
                record.getMessage() == "fact processing attempt failed" for record in caplog.records
            )

        await until("the first attempt failed: the 30 s back-off began", first_attempt_failed)
        await asyncio.sleep(0.3)  # the sleep call follows the log line within the same task step
        began = loop.time()
        await runtime.stop()
        stopped_in = loop.time() - began

    assert stopped_in < 10, (
        f"the stop signal did not end the 30 s back-off: stopping took {stopped_in:.1f} s"
    )
    assert await committed(dl_support, env, group, source, partition) == baseline_offset + 1, (
        "the committed offset (read from the broker) is unchanged by the stop"
    )
    assert await letters_of(dl_support, env.kafka, letters, event_id) == [], (
        "the interrupted record was not dead-lettered"
    )
    lines = [record.getMessage() for record in caplog.records]
    assert not any(line.startswith("fact handler failed") for line in lines), (
        "a stop is not a handler failure"
    )
    assert any(line.startswith("fact retry interrupted by shutdown") for line in lines)

    second = await env.start(group)
    try:

        async def dead_lettered_and_committed() -> bool:
            return bool(
                len(await letters_of(dl_support, env.kafka, letters, event_id)) == 1
                and await committed(dl_support, env, group, source, partition) == offset + 1
            )

        await until(
            "after the restart the record is redelivered, dead-lettered once and committed",
            dead_lettered_and_committed,
            seconds=60,
        )
    finally:
        await second.stop()
