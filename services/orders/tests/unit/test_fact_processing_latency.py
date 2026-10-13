"""R59 / OR9 (S5.2): `otc_fact_processing_latency_ms` as `FactRetry` records it.

The clock advances 240 ms 500 us at EVERY reading, so the entry-to-end span is a multiple of a value
that has a fractional millisecond: integer division gives 240, a missing factor gives 0.2405.
"""

from datetime import UTC, datetime, timedelta

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader

from otc_orders.application.ports.fact_stream import FactMessage
from otc_orders.infrastructure.messaging.fact_retry import (
    DeadLetter,
    FactRetry,
    FactRetryPolicy,
)
from otc_orders.infrastructure.observability.metrics import (
    FactLatencyHistogram,
    fact_processing_latency,
)

START = datetime(2026, 10, 12, 9, 0, 0, tzinfo=UTC)
STEP = timedelta(milliseconds=240, microseconds=500)


class Clock:
    def __init__(self) -> None:
        self.n = 0

    def now(self) -> datetime:
        reading = START + self.n * STEP
        self.n += 1
        return reading


class Publisher:
    def __init__(self) -> None:
        self.letters: list[DeadLetter] = []

    async def publish(self, letter: DeadLetter) -> None:
        self.letters.append(letter)


async def _no_sleep(seconds: float) -> None:
    return None


def _retry(consumer: str, attempts: int) -> tuple[FactRetry, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("test")
    retry = FactRetry(
        consumer=consumer,
        policy=FactRetryPolicy(max_attempts=attempts, backoff_ms=1),
        clock=Clock(),
        sleep=_no_sleep,
        dead_letters=Publisher(),
        latency=FactLatencyHistogram(fact_processing_latency(meter)),
    )
    return retry, reader


def _points(reader: InMemoryMetricReader) -> list[HistogramDataPoint]:
    data = reader.get_metrics_data()
    assert data is not None
    points: list[HistogramDataPoint] = []
    for resource_metrics in data.resource_metrics:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                assert metric.name == "otc_fact_processing_latency_ms"
                for point in metric.data.data_points:
                    assert isinstance(point, HistogramDataPoint)
                    points.append(point)
    return points


def _message() -> FactMessage:
    return FactMessage(topic="t", partition=0, offset=1, key=b"k", value=b"{}", headers=())


async def test_r59_a_successful_fact_records_exactly_240_5_ms_once_under_its_consumer_token() -> (
    None
):
    retry, reader = _retry("orders.saga", attempts=3)

    async def work() -> None:
        return None

    await retry.process(_message(), "credit.approved.v1", work)

    (point,) = _points(reader)
    assert point.sum == 240.5, f"expected 240.5 ms (entry reading to end reading), got {point.sum}"
    assert point.count == 1
    assert dict(point.attributes or {}) == {"consumer": "orders.saga"}


async def test_r59_a_dead_lettered_fact_records_the_exact_sum_of_its_whole_loop_once() -> None:
    retry, reader = _retry("projector", attempts=3)

    async def work() -> None:
        raise ValueError("poison")

    await retry.process(_message(), "credit.approved.v1", work)

    # Readings: entry 0, three failures 1 - 3, the end 4: four steps from entry to end.
    (point,) = _points(reader)
    assert point.sum == 4 * 240.5, f"expected 962.0 ms for the three attempts, got {point.sum}"
    assert point.count == 1
    assert dict(point.attributes or {}) == {"consumer": "projector"}
