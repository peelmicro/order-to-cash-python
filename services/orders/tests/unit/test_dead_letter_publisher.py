# ruff: noqa: E501 - test names are claims, spelled out in full
"""`KafkaDeadLetterPublisher` (`R16`, `OR8`): the dead-letter record, over a RECORDING producer.

Pure: the producer factory is a recorder, so what is asserted is what the publisher handed the
producer (topic, key, value, headers, constructor options), compared with the `DeadLetter` this
test built. The real broker round trip is `test_orders_dead_letter.py`.

Fixture discipline: every header value differs from every other (consumer, topic, event type,
error, both instants), the two instants differ from each other and carry microseconds that
`format_instant` truncates, the value is NOT canonical JSON (spaces, key order, non-ASCII) so a
re-serialisation would change its bytes, and the key is NOT the event type.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider

from otc_orders.infrastructure.messaging.dead_letter_publisher import (
    ERROR_LIMIT,
    KafkaDeadLetterPublisher,
    dead_letter_headers,
)
from otc_orders.infrastructure.messaging.fact_retry import DeadLetter
from otc_orders.infrastructure.observability.trace_context import current_traceparent
from otc_orders.infrastructure.settings import KafkaSettings

FIRST_FAILED_AT = datetime(2026, 10, 12, 9, 15, 30, 123987, tzinfo=UTC)
FAILED_AT = datetime(2026, 10, 12, 9, 15, 31, 987654, tzinfo=UTC)
VALUE = '{ "payload" : {"name": "Ñandú ✓"},  "eventId": "7c1f0c52-0000-4000-8000-000000000001" }'.encode()


def letter(**overrides: Any) -> DeadLetter:
    fields: dict[str, Any] = {
        "source_topic": "otc.billing.facts.v1",
        "key": b"4f1c3a6e-0000-4000-8000-00000000c0de",
        "value": VALUE,
        "consumer": "orders.saga",
        "attempts": 3,
        "error": "ValueError: payload.orderReference is not a reference",
        "first_failed_at": FIRST_FAILED_AT,
        "failed_at": FAILED_AT,
        "event_type": "credit.approved.v1",
    }
    return DeadLetter(**(fields | overrides))


class RecordingProducer:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.started = 0
        self.stopped = 0
        self.sent: list[dict[str, Any]] = []
        self.start_failure: Exception | None = None

    async def start(self) -> None:
        self.started += 1
        if self.start_failure is not None:
            raise self.start_failure

    async def stop(self) -> None:
        self.stopped += 1

    async def send_and_wait(
        self, topic: str, *, value: bytes, key: bytes | None, headers: list[tuple[str, bytes]]
    ) -> object:
        self.sent.append({"topic": topic, "value": value, "key": key, "headers": headers})
        return object()


class Factory:
    def __init__(self, start_failure: Exception | None = None) -> None:
        self.producers: list[RecordingProducer] = []
        self._start_failure = start_failure

    def __call__(self, **options: Any) -> RecordingProducer:
        producer = RecordingProducer(options)
        producer.start_failure = self._start_failure
        self.producers.append(producer)
        return producer


def publisher_over(factory: Factory, brokers: str = "broker-a:19092,broker-b:19092") -> Any:
    return KafkaDeadLetterPublisher(
        KafkaSettings.model_validate({"KAFKA_BROKERS": brokers}),
        client_id="otc-orders-dlq",
        producer_factory=factory,
    )


async def published(dead: DeadLetter) -> dict[str, Any]:
    factory = Factory()
    publisher = publisher_over(factory)
    await publisher.start()
    await publisher.publish(dead)
    [producer] = factory.producers
    [sent] = producer.sent
    return sent


async def test_r16_the_dead_letter_goes_to_the_companion_topic_keyed_by_the_original_key_with_the_original_bytes() -> (
    None
):
    sent = await published(letter())

    assert sent["topic"] == "otc.billing.facts.v1.dlq"
    assert sent["key"] == b"4f1c3a6e-0000-4000-8000-00000000c0de", (
        "the correlation id, not the type"
    )
    assert sent["value"] == VALUE, "the ORIGINAL bytes: a re-serialised envelope would differ"
    assert sent["value"] != b"credit.approved.v1"


async def test_r16_a_record_with_no_key_is_dead_lettered_with_no_key() -> None:
    sent = await published(letter(key=None))

    assert sent["key"] is None


async def test_r16_every_header_value_is_exactly_what_the_failure_was() -> None:
    sent = await published(letter())

    assert dict(sent["headers"]) == {
        "x-failed-consumer": b"orders.saga",
        "x-attempts": b"3",
        "x-error": b"ValueError: payload.orderReference is not a reference",
        "x-original-topic": b"otc.billing.facts.v1",
        "x-first-failed-at": b"2026-10-12T09:15:30.123Z",
        "x-failed-at": b"2026-10-12T09:15:31.987Z",
        "x-event-type": b"credit.approved.v1",
        "content-type": b"application/json",
    }
    assert [name for name, _ in sent["headers"]] == [
        "x-failed-consumer",
        "x-attempts",
        "x-error",
        "x-original-topic",
        "x-first-failed-at",
        "x-failed-at",
        "x-event-type",
        "content-type",
    ], "every header once; no `traceparent` without a span"


async def test_r16_the_two_instants_are_not_transposed_and_are_not_isoformat() -> None:
    headers = dict((await published(letter()))["headers"])

    assert headers["x-first-failed-at"] == b"2026-10-12T09:15:30.123Z"
    assert headers["x-failed-at"] == b"2026-10-12T09:15:31.987Z"
    assert headers["x-first-failed-at"] != headers["x-failed-at"]
    assert b"+00:00" not in headers["x-failed-at"], "isoformat() would write the offset"
    assert b"123987" not in headers["x-first-failed-at"], "milliseconds, truncated"


async def test_r16_x_error_is_cut_at_one_thousand_characters_not_bytes() -> None:
    long = "ValueError: " + "ñ" * 1200

    value = dict((await published(letter(error=long)))["headers"])["x-error"].decode("utf-8")

    assert ERROR_LIMIT == 1000
    assert value == long[:1000]
    assert len(value) == 1000


async def test_r16_a_dead_letter_made_under_a_span_carries_that_spans_traceparent() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("consume") as span:
        headers = dict(dead_letter_headers(letter()))
        current = current_traceparent()
        context = span.get_span_context()

    assert current is not None
    assert headers["traceparent"] == current.encode()
    trace_id = headers["traceparent"].decode().split("-")[1]
    assert trace_id == f"{context.trace_id:032x}"
    provider.shutdown()


async def test_r16_a_dead_letter_made_under_no_span_carries_no_traceparent() -> None:
    assert "traceparent" not in dict(dead_letter_headers(letter()))


async def test_r16_the_producer_is_acknowledged_idempotent_and_connects_to_the_services_own_brokers() -> (
    None
):
    factory = Factory()
    publisher = publisher_over(factory, brokers="kafka.sentinel:19092")

    await publisher.start()

    [producer] = factory.producers
    assert producer.options == {
        "bootstrap_servers": "kafka.sentinel:19092",
        "client_id": "otc-orders-dlq",
        "acks": "all",
        "enable_idempotence": True,
        "request_timeout_ms": 10_000,
    }
    assert producer.started == 1


async def test_or8_publishing_before_the_producer_is_started_raises() -> None:
    with pytest.raises(RuntimeError, match="not started"):
        await publisher_over(Factory()).publish(letter())


async def test_or8_after_stop_the_producer_is_closed_once_and_publishing_raises() -> None:
    factory = Factory()
    publisher = publisher_over(factory)
    await publisher.start()

    await publisher.stop()
    await publisher.stop()

    [producer] = factory.producers
    assert producer.stopped == 1, "stop() is idempotent"
    with pytest.raises(RuntimeError, match="not started"):
        await publisher.publish(letter())


async def test_or8_a_producer_that_fails_to_start_is_closed_and_the_failure_propagates() -> None:
    factory = Factory(start_failure=ConnectionError("no broker"))
    publisher = publisher_over(factory)

    with pytest.raises(ConnectionError, match="no broker"):
        await publisher.start()

    [producer] = factory.producers
    assert producer.stopped == 1, "a producer whose start() raised still holds a client"
