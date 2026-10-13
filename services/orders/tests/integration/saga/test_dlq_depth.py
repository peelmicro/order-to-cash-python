# ruff: noqa: E501 - test names are claims, spelled out in full
"""R59 / OR9 (S5.6): `otc_dlq_depth` per topic, read from a REAL broker.

Three private `.dlq` topics get DIFFERENT depths (2, 5 and 3 records, so a sum of the three, an
average, or the same value everywhere cannot satisfy the assertion); a fourth name does not exist.
The expected value of each is what the TEST reads back from the broker with its own consumer
(`read_records`), cross-checked against what it produced. The missing topic is listed FIRST, so a
reader that raised on it would starve every other topic in the same cycle.

Loop scope: the default (function): the reader's consumer is started and stopped inside the task,
in this test's own loop.
"""

import asyncio
import uuid
from types import ModuleType
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint

from otc_orders.infrastructure.messaging.dlq_depth import DlqDepthTask, KafkaDlqDepth
from otc_orders.infrastructure.observability.metrics import dlq_depth
from otc_orders.infrastructure.settings import KafkaSettings


def _gauge(reader: InMemoryMetricReader) -> dict[str, float]:
    data = reader.get_metrics_data()
    if data is None:
        return {}
    found: dict[str, float] = {}
    for resource_metrics in data.resource_metrics:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                assert metric.name == "otc_dlq_depth"
                for point in metric.data.data_points:
                    assert isinstance(point, NumberDataPoint)
                    found[str((point.attributes or {})["topic"])] = float(point.value)
    return found


async def _produce(support: ModuleType, servers: str, topic: str, count: int) -> None:
    for _ in range(count):
        await support.produce(servers, topic, key=uuid.uuid4().bytes, value=b'{"poison":true}')


async def test_r59_each_dead_letter_topic_reports_the_count_the_broker_holds_and_a_missing_topic_reports_zero_without_starving_the_others(
    dl_support: ModuleType, kafka_server: Any, monkeypatch: pytest.MonkeyPatch, waits: Any
) -> None:
    servers = kafka_server.bootstrap_servers
    monkeypatch.setenv("KAFKA_BROKERS", servers)
    topics = await dl_support.create_private_topics(servers, "dlqdepth")
    first, second, third = topics.dead_letters
    for topic, count in ((first, 2), (second, 5), (third, 3)):
        await _produce(dl_support, servers, topic, count)
    missing = f"otc-dlqdepth-{uuid.uuid4().hex[:10]}-never-created.dlq"
    on_broker = {
        topic: len(await dl_support.read_records(servers, topic)) for topic in topics.dead_letters
    }
    assert on_broker == {first: 2, second: 5, third: 3}, "the fixture is not what the test claims"

    metric_reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[metric_reader]).get_meter("test")
    stop = asyncio.Event()
    task = asyncio.create_task(
        DlqDepthTask(
            KafkaDlqDepth(KafkaSettings(), [missing, first, second, third]),
            dlq_depth(meter),
            poll_interval=0.1,
            enabled=True,
        ).run(stop)
    )
    try:
        expected = {missing: 0.0, first: 2.0, second: 5.0, third: 3.0}

        async def reports_the_broker_counts() -> bool:
            return _gauge(metric_reader) == expected

        await waits(
            reports_the_broker_counts,
            f"the gauge equals the broker's per-topic counts {expected}",
        )

        await _produce(dl_support, servers, second, 1)  # one more, on ONE topic

        async def follows_the_new_record() -> bool:
            return _gauge(metric_reader) == {**expected, second: 6.0}

        await waits(
            follows_the_new_record,
            f"only {second} moves to 6 and the other topics keep their depth",
        )
    finally:
        stop.set()
        async with asyncio.timeout(15):
            await task


async def test_r59_the_depth_reader_is_group_less_and_never_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAFKA_BROKERS", "broker.test:9092")
    options = KafkaDlqDepth(KafkaSettings(), ["a.dlq"]).consumer_options()
    assert options["bootstrap_servers"] == "broker.test:9092"
    assert options["group_id"] is None, "a depth reader must not join a consumer group"
    assert options["enable_auto_commit"] is False
    assert options["client_id"] == "otc-orders-dlq-depth"


async def test_r59_a_reader_that_cannot_start_ends_the_task_with_the_error_so_readiness_sees_it() -> (
    None
):
    class CannotStart:
        async def start(self) -> None:
            raise ConnectionError("no broker")

        async def stop(self) -> None:
            return None

        async def depths(self) -> dict[str, int]:
            raise AssertionError("never reached")

    meter = MeterProvider().get_meter("test")
    task = DlqDepthTask(CannotStart(), dlq_depth(meter), poll_interval=0.1, enabled=True)
    with pytest.raises(ConnectionError, match="no broker"):
        await task.run(asyncio.Event())
