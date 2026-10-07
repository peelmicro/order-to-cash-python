# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`KafkaFactSubscriber` against a fake consumer: the offset contract (SO9, L1-L5, L28, L29).

The fake emulates aiokafka's position semantics, which is what the contract is about: a record
handed out has already advanced the position, so only a `seek` makes it come back. It records every
`getmany`, `commit` and `seek`. No broker; the integration tests (`integration/saga/
test_saga_consumption.py`) prove the same properties against a real one.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiokafka.errors import CommitFailedError

from otc_orders.application.ports.fact_stream import FactMessage
from otc_orders.infrastructure.messaging.fact_topics import SAGA_FACT_TOPICS
from otc_orders.infrastructure.messaging.kafka_fact_subscriber import (
    KafkaFactSubscriber,
    retry_delay_seconds,
)
from otc_orders.infrastructure.settings import KafkaSettings

TP = ("otc.orders.facts.v1", 3)
OTHER_TP = ("otc.billing.facts.v1", 1)


@dataclass(frozen=True)
class FakeRecord:
    topic: str
    partition: int
    offset: int
    key: bytes | None = b"key"
    value: bytes | None = b"{}"
    headers: Sequence[tuple[str, bytes]] = ()


@dataclass
class FakeConsumer:
    """One partition's log; `getmany` hands out the record at the position and advances it."""

    log: list[FakeRecord]
    done: asyncio.Event
    commit_failures: list[BaseException] = field(default_factory=list)
    started: bool = False
    stopped: bool = False
    start_error: BaseException | None = None
    position: int = 0
    seeks: list[tuple[tuple[str, int], int]] = field(default_factory=list)
    commits: list[dict[tuple[str, int], int]] = field(default_factory=list)
    polls: list[tuple[int, int]] = field(default_factory=list)

    async def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def getmany(
        self, *, timeout_ms: int, max_records: int
    ) -> Mapping[tuple[str, int], Sequence[FakeRecord]]:
        self.polls.append((timeout_ms, max_records))
        await asyncio.sleep(0)
        if self.position >= len(self.log):
            self.done.set()  # nothing left: the test is over
            return {}
        record = self.log[self.position]
        self.position += 1  # handed out: the fetch position has moved past it (aiokafka)
        return {(record.topic, record.partition): [record]}

    def seek(self, partition: tuple[str, int], offset: int) -> None:
        self.seeks.append((partition, offset))
        self.position = offset

    async def commit(self, offsets: Mapping[tuple[str, int], int]) -> None:
        if self.commit_failures:
            raise self.commit_failures.pop(0)
        self.commits.append(dict(offsets))


@dataclass
class Harness:
    consumer: FakeConsumer
    stop: asyncio.Event
    factory_calls: list[tuple[tuple[Any, ...], dict[str, Any]]]
    sleeps: list[float]
    subscriber: KafkaFactSubscriber


def settings() -> KafkaSettings:
    return KafkaSettings.model_validate({"KAFKA_BROKERS": "broker.test:9092"})


def harness(offsets: Sequence[int], *, partition: tuple[str, int] = TP) -> Harness:
    stop = asyncio.Event()
    consumer = FakeConsumer(
        log=[FakeRecord(topic=partition[0], partition=partition[1], offset=o) for o in offsets],
        done=stop,
    )
    factory_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    sleeps: list[float] = []

    def factory(*topics: str, **options: Any) -> FakeConsumer:
        factory_calls.append((topics, options))
        return consumer

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return Harness(
        consumer=consumer,
        stop=stop,
        factory_calls=factory_calls,
        sleeps=sleeps,
        subscriber=KafkaFactSubscriber(settings(), consumer_factory=factory, sleep=sleep),
    )


def test_constructing_the_subscriber_builds_no_kafka_client() -> None:
    # Construction outside any running loop: an aiokafka object built here would bind to the wrong
    # loop (L28). The factory is a spy; it must not have been called.
    calls: list[object] = []

    def spy(*topics: str, **options: Any) -> Any:
        calls.append((topics, options))
        raise AssertionError("an aiokafka consumer was built at construction")

    KafkaFactSubscriber(settings(), consumer_factory=spy)

    assert calls == []


async def test_the_consumer_reads_from_earliest_commits_manually_and_uses_the_orders_saga_group_and_client_identity() -> (
    None
):
    h = harness([])

    await h.subscriber.run(_noop_handler, h.stop)

    [(topics, options)] = h.factory_calls
    assert topics == (
        "otc.orders.facts.v1",
        "otc.fulfillment.facts.v1",
        "otc.billing.facts.v1",
    )
    assert topics == SAGA_FACT_TOPICS
    assert options == {
        "bootstrap_servers": "broker.test:9092",
        "group_id": "orders.saga",
        "client_id": "otc-orders-saga",
        "enable_auto_commit": False,
        "auto_offset_reset": "earliest",
    }


async def _noop_handler(_message: FactMessage) -> None:
    return None


async def test_a_successful_record_is_committed_one_past_its_offset_after_the_handler_returned() -> (
    None
):
    h = harness([4])
    events: list[str] = []

    async def handler(message: FactMessage) -> None:
        events.append(f"handled {message.offset}")
        assert h.consumer.commits == [], (
            "the offset must not be committed before the handler returns"
        )

    await h.subscriber.run(handler, h.stop)

    assert events == ["handled 4"]
    assert h.consumer.commits == [{TP: 5}]
    assert h.consumer.seeks == []
    assert h.consumer.polls[0] == (500, 1), "one record per poll: max_records=1"
    assert h.consumer.started
    assert h.consumer.stopped


async def test_the_message_carries_the_records_topic_partition_offset_key_value_and_headers() -> (
    None
):
    h = harness([])
    h.consumer.log = [
        FakeRecord(
            "otc.billing.facts.v1",
            2,
            9,
            key=b"correlation",
            value=b'{"a":1}',
            headers=(("x-event-type", b"payment.received.v1"),),
        )
    ]
    seen: list[FactMessage] = []

    async def handler(message: FactMessage) -> None:
        seen.append(message)

    await h.subscriber.run(handler, h.stop)

    assert seen == [
        FactMessage(
            topic="otc.billing.facts.v1",
            partition=2,
            offset=9,
            key=b"correlation",
            value=b'{"a":1}',
            headers=(("x-event-type", b"payment.received.v1"),),
        )
    ]


async def test_records_are_handled_one_at_a_time_in_partition_order() -> None:
    h = harness([0, 1])
    gate = asyncio.Event()
    started: list[int] = []
    finished: list[int] = []
    first_started = asyncio.Event()

    async def handler(message: FactMessage) -> None:
        started.append(message.offset)
        if message.offset == 0:
            first_started.set()
            await gate.wait()
        finished.append(message.offset)

    run = asyncio.create_task(h.subscriber.run(handler, h.stop))
    await asyncio.wait_for(first_started.wait(), timeout=2)
    await asyncio.sleep(0.05)  # a concurrent implementation would have started offset 1 by now

    assert started == [0], "the second record must wait for the first handler to return"
    assert h.consumer.commits == []

    gate.set()
    await asyncio.wait_for(run, timeout=2)

    assert started == finished == [0, 1]
    assert h.consumer.commits == [{TP: 1}, {TP: 2}]


async def test_a_handler_that_throws_leaves_the_offset_uncommitted_and_the_record_is_delivered_again() -> (
    None
):
    h = harness([0])
    attempts: list[int] = []

    async def handler(message: FactMessage) -> None:
        attempts.append(message.offset)
        if len(attempts) == 1:
            raise RuntimeError("the first delivery fails")

    await h.subscriber.run(handler, h.stop)

    assert attempts == [0, 0], "the same offset is delivered again"
    assert h.consumer.commits == [{TP: 1}], "committed only after the second, successful, delivery"


async def test_a_failed_record_is_sought_back_to_its_own_offset() -> None:
    h = harness([7])
    failed = False

    async def handler(_message: FactMessage) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("boom")

    await h.subscriber.run(handler, h.stop)

    assert h.consumer.seeks == [(TP, 7)]


async def test_so9_a_failed_record_is_never_committed_past_by_a_later_record_of_the_same_partition() -> (
    None
):
    h = harness([0, 1])
    failures_left = 2

    async def handler(message: FactMessage) -> None:
        nonlocal failures_left
        if message.offset == 0 and failures_left:
            failures_left -= 1
            raise RuntimeError("offset 0 keeps failing")

    await h.subscriber.run(handler, h.stop)

    assert h.consumer.commits == [{TP: 1}, {TP: 2}], (
        "offset 1 succeeded only after offset 0, and nothing past offset 0 was committed before"
    )
    assert h.consumer.seeks == [(TP, 0), (TP, 0)]


async def test_a_failure_in_one_partition_does_not_seek_another() -> None:
    h = harness([])
    h.consumer.log = [FakeRecord(*TP, 0), FakeRecord(*OTHER_TP, 0)]

    async def handler(message: FactMessage) -> None:
        if message.topic == TP[0] and not h.consumer.seeks:
            raise RuntimeError("only the first partition fails")

    await h.subscriber.run(handler, h.stop)

    assert [partition for partition, _ in h.consumer.seeks] == [TP]


async def test_redelivery_of_a_failing_record_is_paced_1s_doubling_to_a_30s_cap_and_reset_by_success() -> (
    None
):
    h = harness([0, 1])
    failures = {0: 7, 1: 1}

    async def handler(message: FactMessage) -> None:
        if failures[message.offset]:
            failures[message.offset] -= 1
            raise RuntimeError("fails")

    await h.subscriber.run(handler, h.stop)

    assert h.sleeps == [1, 2, 4, 8, 16, 30, 30, 1], (
        "seven consecutive failures double to the cap; a success resets the pace to 1 s"
    )


def test_the_retry_delay_is_a_pure_function_of_the_consecutive_failures() -> None:
    assert [retry_delay_seconds(n) for n in (1, 2, 3, 4, 5, 6, 7, 1000)] == [
        1,
        2,
        4,
        8,
        16,
        30,
        30,
        30,
    ]


async def test_a_commit_failure_after_a_rebalance_is_logged_and_neither_seeks_nor_stops_the_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = harness([0, 1])
    h.consumer.commit_failures = [CommitFailedError()]
    handled: list[int] = []

    async def handler(message: FactMessage) -> None:
        handled.append(message.offset)

    with caplog.at_level(logging.WARNING):
        await h.subscriber.run(handler, h.stop)

    assert handled == [0, 1], "the next record is still handled"
    assert h.consumer.seeks == [], "a failed commit is not a failed record"
    assert h.consumer.commits == [{TP: 2}]
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.offset == 0  # type: ignore[attr-defined]


async def test_the_consumer_is_stopped_when_the_loop_is_cancelled_and_cancellation_propagates() -> (
    None
):
    h = harness([0])
    entered = asyncio.Event()

    async def handler(_message: FactMessage) -> None:
        entered.set()
        await asyncio.Event().wait()

    run = asyncio.create_task(h.subscriber.run(handler, h.stop))
    await asyncio.wait_for(entered.wait(), timeout=2)
    run.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run
    assert h.consumer.stopped
    assert h.consumer.commits == [], "a cancelled handler is not a success"


async def test_a_consumer_that_cannot_start_is_stopped_and_the_error_reaches_the_task() -> None:
    h = harness([])
    h.consumer.start_error = ConnectionError("no broker")

    with pytest.raises(ConnectionError, match="no broker"):
        await h.subscriber.run(_noop_handler, h.stop)

    assert h.consumer.stopped
