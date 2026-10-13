# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R59` / `OR9` in Notifications' REAL composition (S8a; #8's `RealInfraMetricsProvenanceTests`).

`FactRetry`'s arithmetic is proved with an injected instrument; nothing there touches the
composition root, whose `latency=` argument defaults to a no-op. Here the real `start_runtime` runs
with an in-memory metric reader on its OWN meter provider, a real Kafka-delivered fact is processed,
and the reader holds what the runtime recorded.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader

FAST = {"FACT_RETRY_BACKOFF_MS": "20", "NOTIFICATIONS_SENDER": "console"}


def histogram_points(reader: InMemoryMetricReader, name: str) -> list[HistogramDataPoint]:
    data = reader.get_metrics_data()
    points: list[HistogramDataPoint] = []
    for resource in data.resource_metrics if data is not None else ():
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name == name:
                    points.extend(
                        p for p in metric.data.data_points if isinstance(p, HistogramDataPoint)
                    )
    return points


async def until(
    claim: str, condition: Callable[[], Awaitable[bool]], seconds: float = 30.0
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not await condition():
        if loop.time() > deadline:
            pytest.fail(f"{claim}: not observed within {seconds} s")
        await asyncio.sleep(0.1)


async def test_r59_a_real_kafka_fact_notifications_processes_records_its_processing_latency_through_the_runtimes_own_meter(
    notifications_host_factory: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    facts: Any,
) -> None:
    reader = InMemoryMetricReader()
    event = facts.with_values("order.placed.v1", event_id=uuid.uuid4())
    async with notifications_host_factory(topics=private_topics, metric_readers=[reader], **FAST):
        await dl_support.produce(
            kafka_server.bootstrap_servers,
            private_topics.orders,
            key=str(event.correlation_id).encode(),
            value=facts.wire_from(event),
        )

        async def recorded() -> bool:
            return bool(histogram_points(reader, "otc_fact_processing_latency_ms"))

        await until(
            "the runtime's meter holds the fact processing latency (otc_fact_processing_latency_ms)",
            recorded,
        )

    points = histogram_points(reader, "otc_fact_processing_latency_ms")
    assert [(dict(p.attributes or {}), p.count) for p in points] == [
        ({"consumer": "notifications"}, 1)
    ], "one fact processed, one record, tagged with the consumer token"
    assert points[0].sum > 0
