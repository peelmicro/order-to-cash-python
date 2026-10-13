# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R59` / `OR9` in the REAL runtime (S8a; #8's `RealInfraMetricsProvenanceTests`).

`test_fact_processing_latency.py` and `test_fact_handler.py` prove the arithmetic and the outcomes
with the instruments injected; neither touches the composition root, so a composition that forgot
to bind `SagaCompletionHistogram` or `FactLatencyHistogram` (both ports default to a no-op) passed
every test. Here the real `start_runtime` is booted with an in-memory metric reader handed to the
runtime's OWN meter provider, a real Kafka-delivered `stock.rejected.v1` closes a placed order, and
what the reader holds is what the runtime recorded.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader

from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


def histogram_points(reader: InMemoryMetricReader, name: str) -> list[HistogramDataPoint]:
    """Every data point of the histogram `name` the reader has collected (empty if none)."""
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


async def test_r59_a_real_kafka_fact_that_closes_the_saga_records_its_completion_and_its_latency_through_the_runtimes_own_meter(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    reader = InMemoryMetricReader()
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness(metric_readers=[reader]) as saga:
        await saga.publish_fact(
            "stock.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def completion_recorded() -> bool:
            return bool(histogram_points(reader, "otc_saga_completion_ms"))

        async def latency_recorded() -> bool:
            return bool(histogram_points(reader, "otc_fact_processing_latency_ms"))

        await waits(
            completion_recorded,
            "the runtime's meter holds the saga completion (otc_saga_completion_ms)",
        )
        await waits(
            latency_recorded,
            "the runtime's meter holds the fact processing latency (otc_fact_processing_latency_ms)",
        )
        assert await saga.db.status_of(order.id) == "cancelled"

    completions = histogram_points(reader, "otc_saga_completion_ms")
    assert [(dict(p.attributes or {}), p.count) for p in completions] == [
        ({"outcome": "cancelled"}, 1)
    ], "one closed saga, one record, tagged with the outcome"
    assert completions[0].sum > 0, "the elapsed time from the order date to the close"
    latencies = histogram_points(reader, "otc_fact_processing_latency_ms")
    assert [(dict(p.attributes or {}), p.count) for p in latencies] == [
        ({"consumer": "orders.saga"}, 1)
    ], "one fact consumed, one record, tagged with the consumer token"
