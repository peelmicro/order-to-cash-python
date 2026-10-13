# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R16` for Notifications, through the REAL composition (S4.19, S4.24).

Every topic is private to the test (item 10). A poison is a notified type (`order.placed.v1`) whose
payload fails its model; a TRANSIENT SMTP failure is a genuine `451` forced by Mailpit's chaos API
and a PERMANENT one a genuine `550`. The dead letters are read from the broker by content after a
decoy; the committed offsets are the group's as the broker reports them.
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

from otc_contracts import from_wire_json
from otc_notifications.infrastructure.notification.smtp_sender import SmtpNotificationSender
from otc_notifications.presentation import notification_facts_consumer

INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
FAST = {"FACT_RETRY_BACKOFF_MS": "20", "NOTIFICATIONS_SENDER": "console"}
TRANSACTION = "writemodel.transaction"


async def until(
    claim: str, condition: Callable[[], Awaitable[bool]], seconds: float = 30.0
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not await condition():
        if loop.time() > deadline:
            pytest.fail(f"{claim}: not observed within {seconds} s")
        await asyncio.sleep(0.1)


def poison_bytes(facts: Any, event_id: uuid.UUID) -> bytes:
    """A well-formed envelope whose payload fails `order.placed.v1`'s model, written the way no
    serializer would: keys reversed, spaces in the separators, an undeclared top-level field,
    non-ASCII text."""
    document = json.loads(facts.wire_from(facts.with_values("order.placed.v1", event_id=event_id)))
    document["payload"]["orderReference"] = 42  # an int where the model wants "ORD-nnnnnn"
    document["payload"]["note"] = "ñandú 日本"
    document["zzUndeclared"] = True
    return json.dumps(
        dict(reversed(list(document.items()))), separators=(", ", ": "), ensure_ascii=False
    ).encode("utf-8")


def expected_error(facts: Any, produced: bytes) -> str:
    """What the validation says about `produced`, computed here by running it on the same bytes."""
    model = type(facts.event("order.placed.v1"))
    try:
        from_wire_json(model, produced)
    except ValueError as error:
        return f"{type(error).__name__}: {error}"[:1000]
    raise AssertionError("the poison validated: it is not a poison")


class Attempts:
    """Counts the parses of ONE event id by the wrapped callable (the attempts the wrapper made)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, event_id: uuid.UUID) -> None:
        self.count = 0
        original = from_wire_json

        def counting(model: Any, data: str | bytes) -> Any:
            if not getattr(model, "__name__", "").startswith("Envelope") and json.loads(data).get(
                "eventId"
            ) == str(event_id):
                self.count += 1
            return original(model, data)

        monkeypatch.setattr(notification_facts_consumer, "from_wire_json", counting)


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


async def letters_of(
    dl_support: ModuleType, servers: str, topic: str, event_id: uuid.UUID
) -> list[Any]:
    return [
        record
        for record in await dl_support.read_records(servers, topic)
        if record.event_id == str(event_id)
    ]


async def committed(
    dl_support: ModuleType, servers: str, group: str, topics: Any, topic: str, partition: int
) -> int | None:
    offsets = await dl_support.committed_offsets_of(servers, group, topics.all)
    found: int | None = offsets.get((topic, partition))
    return found


async def decoy_letter(dl_support: ModuleType, servers: str, letters: str, facts: Any) -> None:
    """A dead letter of ANOTHER event, published first on the topic the test reads."""
    await dl_support.produce(
        servers,
        letters,
        key=b"decoy",
        value=facts.wire_from(facts.with_values("order.placed.v1", event_id=uuid.uuid4())),
    )


async def test_r16_a_poison_fact_is_retried_then_dead_lettered_byte_for_byte_with_every_header_and_the_committed_offset_read_from_the_broker_moves_past_it(
    notifications_host_factory: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    facts: Any,
    ledger_rows: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    letters = private_topics.dead_letter_of(source)
    event_id = uuid.uuid4()
    produced = poison_bytes(facts, event_id)
    correlation = facts.event("order.placed.v1").correlation_id
    attempts = Attempts(monkeypatch, event_id)
    await decoy_letter(dl_support, servers, letters, facts)

    async with notifications_host_factory(topics=private_topics, **FAST) as host:
        before = datetime.now(UTC)
        partition, offset = await dl_support.produce(
            servers, source, key=str(correlation).encode(), value=produced
        )

        async def dead_lettered() -> bool:
            return len(await letters_of(dl_support, servers, letters, event_id)) == 1

        await until("the poison's dead letter is on the private .dlq", dead_lettered)

        async def committed_past() -> bool:
            return bool(
                await committed(dl_support, servers, host.group, private_topics, source, partition)
                == offset + 1
            )

        await until(
            "the group's committed offset (read from the broker) is poison + 1", committed_past
        )

        [letter] = await letters_of(dl_support, servers, letters, event_id)
        assert attempts.count == 3, "the wrapper attempted the processing exactly three times"
        assert letter.value == produced, "the ORIGINAL bytes, not a re-serialisation"
        assert letter.key == str(correlation).encode(), "keyed by the original record key"
        headers = letter.headers
        assert headers["x-failed-consumer"] == b"notifications"
        assert headers["x-attempts"] == b"3"
        assert headers["x-error"].decode() == expected_error(facts, produced)
        assert headers["x-original-topic"] == source.encode()
        assert headers["x-event-type"] == b"order.placed.v1"
        assert headers["content-type"] == b"application/json"
        first, final = headers["x-first-failed-at"].decode(), headers["x-failed-at"].decode()
        assert INSTANT.match(first), first
        assert INSTANT.match(final), final
        assert first < final, "20 ms and 40 ms of back-off separate the first failure from the last"
        assert datetime.fromisoformat(first.replace("Z", "+00:00")) >= before - timedelta(
            milliseconds=1
        )

        # the partition moves on: a next, valid fact with the SAME key is processed and committed
        next_event = facts.with_values("order.placed.v1", event_id=uuid.uuid4())
        next_partition, next_offset = await dl_support.produce(
            servers, source, key=str(correlation).encode(), value=facts.wire_from(next_event)
        )
        assert next_partition == partition

        async def processed() -> bool:
            return bool(
                (next_event.event_id, "notifications") in await ledger_rows()
                and await committed(
                    dl_support, servers, host.group, private_topics, source, partition
                )
                == next_offset + 1
            )

        await until("the next fact of the same key is processed and committed", processed)
        assert len(await letters_of(dl_support, servers, letters, event_id)) == 1


async def test_r57_the_consume_span_continues_the_inbound_trace_and_the_dead_letter_carries_it(
    notifications_host_factory: Any,
    private_topics: Any,
    dl_support: ModuleType,
    trace_support: ModuleType,
    kafka_server: Any,
    facts: Any,
) -> None:
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    letters = private_topics.dead_letter_of(source)
    event_id = uuid.uuid4()
    correlation = facts.event("order.placed.v1").correlation_id
    exporter = InMemorySpanExporter()
    with trace_support.caller_tracer().start_as_current_span("fact producer") as origin:
        inbound_context = origin.get_span_context()
        inbound = trace_support.traceparent_header_of_current_span()["traceparent"]

    async with notifications_host_factory(
        topics=private_topics, span_processors=[SimpleSpanProcessor(exporter)], **FAST
    ):
        await dl_support.produce(
            servers,
            source,
            key=str(correlation).encode(),
            value=poison_bytes(facts, event_id),
            headers=[("traceparent", inbound.encode("ascii"))],
        )

        async def dead_lettered() -> bool:
            return len(await letters_of(dl_support, servers, letters, event_id)) == 1

        await until("the poison's dead letter is on the private .dlq", dead_lettered)
        [letter] = await letters_of(dl_support, servers, letters, event_id)

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
    notifications_host_factory: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    facts: Any,
) -> None:
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    letters = private_topics.dead_letter_of(source)
    group = f"notifications-or8-{uuid.uuid4().hex[:8]}"
    event_id = uuid.uuid4()
    correlation = facts.event("order.placed.v1").correlation_id
    refused: list[str] = []

    async with notifications_host_factory(
        topics=private_topics,
        dead_letter_producer_factory=lambda **options: Refusing(refused, **options),
        NOTIFICATIONS_CONSUMER_GROUP=group,
        **FAST,
    ):
        # a valid fact of the SAME key is processed and committed first: the committed offset is a
        # real position, and the poison is the very next offset of its partition
        baseline = facts.with_values("order.placed.v1", event_id=uuid.uuid4())
        partition, baseline_offset = await dl_support.produce(
            servers, source, key=str(correlation).encode(), value=facts.wire_from(baseline)
        )

        async def baseline_committed() -> bool:
            return bool(
                await committed(dl_support, servers, group, private_topics, source, partition)
                == baseline_offset + 1
            )

        await until("the baseline fact is committed", baseline_committed)
        _, offset = await dl_support.produce(
            servers, source, key=str(correlation).encode(), value=poison_bytes(facts, event_id)
        )
        assert offset == baseline_offset + 1

        async def refused_twice() -> bool:
            return len(refused) >= 2

        await until(
            "the publication was refused twice: the record was DELIVERED AGAIN after the first refusal",
            refused_twice,
            seconds=60,
        )
        assert (
            await committed(dl_support, servers, group, private_topics, source, partition)
            == baseline_offset + 1
        ), "the committed offset (read from the broker) is unchanged: the poison is not committed"
        assert await letters_of(dl_support, servers, letters, event_id) == []

    async with notifications_host_factory(
        topics=private_topics, NOTIFICATIONS_CONSUMER_GROUP=group, **FAST
    ):

        async def dead_lettered_and_committed() -> bool:
            return bool(
                len(await letters_of(dl_support, servers, letters, event_id)) == 1
                and await committed(dl_support, servers, group, private_topics, source, partition)
                == offset + 1
            )

        await until(
            "the restarted consumer redelivers the record: one dead letter, committed offset poison + 1",
            dead_lettered_and_committed,
            seconds=60,
        )


async def test_r16_a_transient_smtp_failure_is_sent_three_times_with_the_ledger_row_forgotten_each_time_then_dead_lettered(
    notifications_host_factory: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    facts: Any,
    inbox: Any,
    ledger_rows: Any,
    trace_support: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine `451` to MAIL FROM (Mailpit's chaos API). Each attempt records the ledger row,
    tries the send, FORGETS the row and raises; the next attempt is therefore a real send again
    (three sends observed), and the third failure goes to the `.dlq`."""
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    letters = private_topics.dead_letter_of(source)
    event = facts.with_values("order.placed.v1", event_id=uuid.uuid4())
    produced = facts.wire_from(event)
    await decoy_letter(dl_support, servers, letters, facts)
    await inbox.set_chaos(Sender=(451, 100))
    sends: list[uuid.UUID] = []
    original = SmtpNotificationSender.send
    exporter = InMemorySpanExporter()

    async def counting(self: SmtpNotificationSender, message: Any) -> None:
        sends.append(uuid.UUID(message.message_id.split("@")[0]))
        await original(self, message)

    monkeypatch.setattr(SmtpNotificationSender, "send", counting)

    async with notifications_host_factory(
        topics=private_topics,
        span_processors=[SimpleSpanProcessor(exporter)],
        FACT_RETRY_BACKOFF_MS="20",
    ):
        await dl_support.produce(
            servers, source, key=str(event.correlation_id).encode(), value=produced
        )

        async def three_sends() -> bool:
            return len(sends) >= 3

        await until(
            "three sends were attempted: the ledger row is forgotten after each failed one",
            three_sends,
        )

        async def dead_lettered() -> bool:
            return len(await letters_of(dl_support, servers, letters, event.event_id)) == 1

        await until("the transient failure is dead-lettered after three attempts", dead_lettered)
        [letter] = await letters_of(dl_support, servers, letters, event.event_id)

    assert sends == [event.event_id] * 3, (
        "three genuine sends: the ledger row was forgotten each time"
    )
    assert letter.value == produced
    assert letter.headers["x-attempts"] == b"3"
    assert letter.headers["x-failed-consumer"] == b"notifications"
    error = letter.headers["x-error"].decode()
    assert error.startswith("SMTP"), error
    assert "451" in error, error
    assert await ledger_rows() == [], "the row was forgotten after the final failure too"
    assert await inbox.count() == 0
    # the forget is its own write-model transaction (S3 finding 2): per attempt one `record`
    # transaction and one `forget` transaction, six in all, every one inside the consume span
    infos = trace_support.span_infos(exporter)
    consumers = [
        info
        for info in infos
        if info.kind == trace.SpanKind.CONSUMER and info.name == f"{source} process"
    ]
    transactions = [info for info in infos if info.name == TRANSACTION]
    assert len(consumers) == 1, "the three attempts happen under ONE consume span"
    assert len(transactions) == 6, (
        f"3 record + 3 forget transactions expected, found {len(transactions)}"
    )
    assert {info.parent_id for info in transactions} == {consumers[0].span_id}, (
        "each transaction span is a child of the consume span"
    )


async def test_r16_a_permanent_smtp_failure_is_degraded_once_and_never_dead_lettered(
    notifications_host_factory: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    facts: Any,
    inbox: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A genuine `550`: the console renders it, ONE degraded line is written, the offset commits
    and the `.dlq` (which holds a decoy, so the read is not vacuous) gets nothing for this fact."""
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    letters = private_topics.dead_letter_of(source)
    event = facts.with_values("order.placed.v1", event_id=uuid.uuid4())
    await decoy_letter(dl_support, servers, letters, facts)
    await inbox.set_chaos(Sender=(550, 100))

    with caplog.at_level(logging.INFO):
        async with notifications_host_factory(
            topics=private_topics, FACT_RETRY_BACKOFF_MS="20"
        ) as host:
            partition, offset = await dl_support.produce(
                servers,
                source,
                key=str(event.correlation_id).encode(),
                value=facts.wire_from(event),
            )

            async def committed_past() -> bool:
                return bool(
                    await committed(
                        dl_support, servers, host.group, private_topics, source, partition
                    )
                    == offset + 1
                )

            await until("the permanently refused fact is acknowledged (committed)", committed_past)

    degraded = [
        r for r in caplog.records if getattr(r, "event", None) == "notification.send.degraded"
    ]
    assert len(degraded) == 1, "ONE loud degraded line for the one refused fact"
    assert await letters_of(dl_support, servers, letters, event.event_id) == [], (
        "a permanent failure is never dead-lettered"
    )
    decoys = await dl_support.read_records(servers, letters)
    assert len(decoys) == 1, "the .dlq holds only the decoy: the read was not vacuous"
    assert await inbox.count() == 0


async def test_f1_a_stop_during_a_long_backoff_returns_within_a_small_bound_with_the_offset_unchanged_and_nothing_on_the_dlq_and_the_record_is_redelivered_after_the_restart(
    notifications_host_factory: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    facts: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    letters = private_topics.dead_letter_of(source)
    group = f"notifications-f1-{uuid.uuid4().hex[:8]}"
    event_id = uuid.uuid4()
    correlation = facts.event("order.placed.v1").correlation_id
    loop = asyncio.get_running_loop()
    stopped_in = -1.0

    with caplog.at_level(logging.INFO):
        host_context = notifications_host_factory(
            topics=private_topics,
            NOTIFICATIONS_CONSUMER_GROUP=group,
            **(FAST | {"FACT_RETRY_BACKOFF_MS": "30000"}),
        )
        host = await host_context.__aenter__()
        try:
            baseline = facts.with_values("order.placed.v1", event_id=uuid.uuid4())
            partition, baseline_offset = await dl_support.produce(
                servers, source, key=str(correlation).encode(), value=facts.wire_from(baseline)
            )

            async def baseline_committed() -> bool:
                return bool(
                    await committed(dl_support, servers, group, private_topics, source, partition)
                    == baseline_offset + 1
                )

            await until("the baseline fact is committed", baseline_committed)
            _, offset = await dl_support.produce(
                servers, source, key=str(correlation).encode(), value=poison_bytes(facts, event_id)
            )

            async def first_attempt_failed() -> bool:
                return any(
                    record.getMessage() == "fact processing attempt failed"
                    for record in caplog.records
                )

            await until("the first attempt failed: the 30 s back-off began", first_attempt_failed)
            await asyncio.sleep(
                0.3
            )  # the sleep call follows the log line within the same task step
        finally:
            began = loop.time()
            await host_context.__aexit__(None, None, None)
            stopped_in = loop.time() - began
        assert host is not None

    assert stopped_in < 10, (
        f"the stop signal did not end the 30 s back-off: stopping took {stopped_in:.1f} s"
    )
    assert (
        await committed(dl_support, servers, group, private_topics, source, partition)
        == baseline_offset + 1
    ), "the committed offset (read from the broker) is unchanged by the stop"
    assert await letters_of(dl_support, servers, letters, event_id) == [], (
        "the interrupted record was not dead-lettered"
    )
    lines = [record.getMessage() for record in caplog.records]
    assert not any(line.startswith("fact handler failed") for line in lines), (
        "a stop is not a handler failure"
    )
    assert any(line.startswith("fact retry interrupted by shutdown") for line in lines)

    async with notifications_host_factory(
        topics=private_topics, NOTIFICATIONS_CONSUMER_GROUP=group, **FAST
    ):

        async def dead_lettered_and_committed() -> bool:
            return bool(
                len(await letters_of(dl_support, servers, letters, event_id)) == 1
                and await committed(dl_support, servers, group, private_topics, source, partition)
                == offset + 1
            )

        await until(
            "after the restart the record is redelivered, dead-lettered once and committed",
            dead_lettered_and_committed,
            seconds=60,
        )
