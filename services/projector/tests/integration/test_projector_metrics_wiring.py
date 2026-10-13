# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R59` / `OR9` in the Projector's REAL runtime (S8a; #8's `RealInfraMetricsProvenanceTests`).

`FactRetry`'s arithmetic is proved with an injected instrument; nothing there touches the
composition root, whose `latency=` argument defaults to a no-op. Here the real `start_runtime` runs
with an in-memory metric reader on its OWN meter provider, a real Kafka-delivered fact is projected,
and the reader holds what the runtime recorded.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader

pytestmark = pytest.mark.integration


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


async def test_r59_a_real_kafka_fact_the_projector_projects_records_its_processing_latency_through_the_runtimes_own_meter(
    runtime_env: Any, dl_support: Any, facts: Any, new_reference: Any
) -> None:
    env = runtime_env
    order = uuid.uuid4()
    reader = InMemoryMetricReader()
    runtime = await env.start(f"pm-{uuid.uuid4().hex[:8]}", metric_readers=[reader])
    try:
        await dl_support.produce(
            env.kafka,
            env.topics.orders,
            key=str(order).encode(),
            value=facts.wire(
                facts.build(
                    "order.placed.v1",
                    correlation_id=order,
                    payload={"order_reference": new_reference()},
                )
            ),
        )

        async def recorded() -> bool:
            return bool(histogram_points(reader, "otc_fact_processing_latency_ms"))

        await until(
            "the runtime's meter holds the fact processing latency (otc_fact_processing_latency_ms)",
            recorded,
        )
    finally:
        await runtime.stop()

    points = histogram_points(reader, "otc_fact_processing_latency_ms")
    assert [(dict(p.attributes or {}), p.count) for p in points] == [
        ({"consumer": "projector"}, 1)
    ], "one fact projected, one record, tagged with the consumer token"
    assert points[0].sum > 0
