# ruff: noqa: E501 - test names are claims, spelled out in full
"""R59 / OR9 (S5.4): `otc_outbox_lag_ms` as the PRODUCTION relay sets it, against a real PostgreSQL.

The relay's clock is fixed, the rows' `occurred_at` are planted at known offsets from it (on the
millisecond grid the column stores), so the expected gauge value is arithmetic, not a measurement.
Loop scope: the default (function), as `test_outbox_relay.py`.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint

from otc_orders.infrastructure.observability.metrics import outbox_lag
from otc_orders.infrastructure.outbox.relay import OutboxRelay

NOW = datetime(2026, 10, 12, 12, 0, 0, 0, tzinfo=UTC)
OLDER = timedelta(seconds=7, milliseconds=123)
NEWER = timedelta(seconds=3, milliseconds=456)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class RecordingPublisher:
    def __init__(self) -> None:
        self.published = 0

    async def publish(self, facts: Sequence[Any]) -> None:
        self.published += len(facts)


def _gauge(reader: InMemoryMetricReader) -> float:
    data = reader.get_metrics_data()
    assert data is not None, "the relay's meter exported nothing"
    points: list[NumberDataPoint] = []
    for resource_metrics in data.resource_metrics:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                assert metric.name == "otc_outbox_lag_ms"
                points.extend(
                    point for point in metric.data.data_points if isinstance(point, NumberDataPoint)
                )
    (point,) = points
    return float(point.value)


async def test_r59_the_gauge_is_the_age_of_the_older_of_two_unpublished_rows_then_zero_after_the_drain(
    row_planter: Any, sessions: Any
) -> None:
    await row_planter.plant(occurred_at=NOW - NEWER)
    await row_planter.plant(occurred_at=NOW - OLDER)  # planted second: seq order is not age order
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("test")
    publisher = RecordingPublisher()
    relay = OutboxRelay(
        sessions=sessions,
        publisher=publisher,
        clock=FixedClock(),
        batch_size=100,
        publish_timeout=5.0,
        lag=outbox_lag(meter),
    )

    await relay.run_once()  # the lag is read at the start of the cycle that drains both rows
    assert publisher.published == 2
    assert _gauge(reader) == 7123.0, "the gauge must be the OLDER row's age, in exact milliseconds"

    await relay.run_once()  # nothing pending now
    assert _gauge(reader) == 0.0, "a drained outbox reports 0"


async def test_r59_a_relay_built_without_the_gauge_still_publishes(
    row_planter: Any, sessions: Any
) -> None:
    await row_planter.plant(occurred_at=NOW - OLDER)
    publisher = RecordingPublisher()
    relay = OutboxRelay(
        sessions=sessions,
        publisher=publisher,
        clock=FixedClock(),
        batch_size=100,
        publish_timeout=5.0,
    )
    assert (await relay.run_once()).published == 1
