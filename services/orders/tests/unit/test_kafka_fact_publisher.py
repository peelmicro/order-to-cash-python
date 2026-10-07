"""The Kafka adapter's contract that needs no broker (feature 14, 4.2 and 4.4).

* The topic constant is compared with the `ordersFacts` channel `address` read from
  `specs/shared/asyncapi.yaml`: the spec is the authority, the constant is not.
* OI7: the producer options (what `start()` passes) make an internal retry unable to reorder or
  duplicate.
* L23: constructing the publisher builds no aiokafka object; `start()` builds exactly one, inside
  the running loop. (Loop affinity: an `AIOKafkaProducer` binds to the loop that creates it.)
"""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from otc_orders.infrastructure.outbox import kafka_publisher
from otc_orders.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_orders.infrastructure.outbox.publisher import FactPublicationError, PublishableFact
from otc_orders.infrastructure.outbox.topic import ORDERS_FACTS_TOPIC
from otc_orders.infrastructure.settings import KafkaSettings

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"


def test_the_orders_facts_topic_is_the_asyncapi_orders_facts_address() -> None:
    document = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    address = document["channels"]["ordersFacts"]["address"]
    assert address == ORDERS_FACTS_TOPIC, (
        f"the constant is {ORDERS_FACTS_TOPIC!r}, the spec's ordersFacts address is {address!r}"
    )


def test_oi7_producer_is_idempotent_so_an_internal_retry_can_neither_reorder_nor_duplicate() -> (
    None
):
    options = KafkaFactPublisher(KafkaSettings()).producer_options()
    assert options["enable_idempotence"] is True
    assert options["acks"] == "all"
    assert options["bootstrap_servers"] == "localhost:9092"
    assert options["client_id"] == "otc-orders"


class RecordingProducer:
    constructed: list[RecordingProducer] = []  # noqa: RUF012 - a test recorder

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.started = False
        self.stopped = False
        RecordingProducer.constructed.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def test_constructing_the_publisher_outside_a_running_loop_builds_no_kafka_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingProducer.constructed.clear()
    monkeypatch.setattr(kafka_publisher, "AIOKafkaProducer", RecordingProducer)
    KafkaFactPublisher(KafkaSettings())  # a sync test: no running loop exists here
    assert RecordingProducer.constructed == []


async def test_start_inside_a_running_loop_constructs_exactly_one_producer_and_stop_stops_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingProducer.constructed.clear()
    monkeypatch.setattr(kafka_publisher, "AIOKafkaProducer", RecordingProducer)
    publisher = KafkaFactPublisher(KafkaSettings())
    await publisher.start()
    assert len(RecordingProducer.constructed) == 1
    (producer,) = RecordingProducer.constructed
    assert producer.started
    assert producer.options == publisher.producer_options()
    await publisher.stop()
    assert producer.stopped


class FuturesProducer:
    """Hands back one future per `send`: resolved, or failed with its own exception."""

    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self._outcomes = outcomes
        self.futures: list[asyncio.Future[object]] = []
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, topic: str, **kwargs: Any) -> asyncio.Future[object]:
        self.sent.append((topic, kwargs))
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        outcome = self._outcomes[len(self.futures)]
        if outcome is None:
            future.set_result(object())
        else:
            future.set_exception(outcome)
        self.futures.append(future)
        return future


def fact(n: int) -> PublishableFact:
    return PublishableFact(
        event_id=uuid.UUID(int=n),
        key=f"key-{n}".encode(),
        value=f"value-{n}".encode(),
        headers=((f"header-{n}", f"x-{n}".encode()),),
    )


async def test_a_batch_with_two_failed_records_names_every_failed_event_id_and_retrieves_every_exception() -> (  # noqa: E501
    None
):
    """L25: every future's exception is retrieved, or asyncio logs 'Future exception was never
    retrieved' for the ones `gather` left behind, and only the FIRST failure would be reported."""
    producer = FuturesProducer([None, RuntimeError("second failed"), RuntimeError("third failed")])
    publisher = KafkaFactPublisher(KafkaSettings())
    publisher._producer = producer  # the unit test installs a producer without a broker
    with pytest.raises(FactPublicationError) as raised:
        await publisher.publish([fact(1), fact(2), fact(3)])
    assert raised.value.event_ids == (uuid.UUID(int=2), uuid.UUID(int=3)), "both failures named"
    assert "second failed" in str(raised.value), "the reason is the FIRST failure's"
    assert [future._log_traceback for future in producer.futures] == [False, False, False]


async def test_publish_sends_every_fact_to_the_orders_topic_with_its_own_key_value_and_headers_in_order() -> (  # noqa: E501
    None
):
    producer = FuturesProducer([None, None])
    publisher = KafkaFactPublisher(KafkaSettings())
    publisher._producer = producer
    await publisher.publish([fact(1), fact(2)])
    assert producer.sent == [
        (
            ORDERS_FACTS_TOPIC,
            {"value": b"value-1", "key": b"key-1", "headers": [("header-1", b"x-1")]},
        ),
        (
            ORDERS_FACTS_TOPIC,
            {"value": b"value-2", "key": b"key-2", "headers": [("header-2", b"x-2")]},
        ),
    ]


async def test_publishing_before_start_fails_naming_every_event_id_and_the_reason() -> None:
    publisher = KafkaFactPublisher(KafkaSettings())
    with pytest.raises(FactPublicationError) as raised:
        await publisher.publish([fact(1), fact(2)])
    assert raised.value.event_ids == (uuid.UUID(int=1), uuid.UUID(int=2))
    assert "not started" in str(raised.value)


class RaisingSendProducer:
    """`send` itself raises for the second fact (synchronously, before any future exists)."""

    def __init__(self) -> None:
        self.keys: list[bytes] = []

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, topic: str, **kwargs: Any) -> asyncio.Future[object]:
        self.keys.append(kwargs["key"])
        if len(self.keys) == 2:
            raise RuntimeError("buffer full")
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        future.set_result(object())
        return future


async def test_a_send_that_raises_stops_the_batch_and_names_that_fact_and_every_later_one() -> None:
    """OI8 at the adapter: a later fact is never sent ahead of an earlier one that failed."""
    producer = RaisingSendProducer()
    publisher = KafkaFactPublisher(KafkaSettings())
    publisher._producer = producer
    with pytest.raises(FactPublicationError) as raised:
        await publisher.publish([fact(1), fact(2), fact(3)])
    assert raised.value.event_ids == (uuid.UUID(int=2), uuid.UUID(int=3)), "fact 2 and every later"
    assert producer.keys == [b"key-1", b"key-2"], "fact 3 was never sent"
    assert "send failed" in str(raised.value)
