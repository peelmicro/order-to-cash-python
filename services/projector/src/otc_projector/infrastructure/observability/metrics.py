"""The five instrument names and their factories (`R59`, `OR9`; the spec's `design.md` 6).

Copy of `services/orders/src/otc_orders/infrastructure/observability/metrics.py`.

The canonical is Orders'; `tests/architecture/test_observability_copy_parity.py` fails
on any difference after this docstring. Edit the canonical, then copy.
"""

from collections.abc import Mapping
from typing import Protocol

from opentelemetry.metrics import Histogram, Meter

REQUEST_LATENCY = "otc_request_latency_ms"
FACT_PROCESSING_LATENCY = "otc_fact_processing_latency_ms"
SAGA_COMPLETION = "otc_saga_completion_ms"
OUTBOX_LAG = "otc_outbox_lag_ms"
DLQ_DEPTH = "otc_dlq_depth"


class Gauge(Protocol):
    """The synchronous gauge `Meter.create_gauge` returns. The API exports it only under a private
    name (`opentelemetry.metrics._Gauge`, 1.45.0), so the one method used is named here."""

    def set(self, amount: float, attributes: Mapping[str, str] | None = None) -> None: ...


METRIC_NAMES = (REQUEST_LATENCY, FACT_PROCESSING_LATENCY, SAGA_COMPLETION, OUTBOX_LAG, DLQ_DEPTH)


def request_latency(meter: Meter) -> Histogram:
    """Gateway: milliseconds per request, attribute `endpoint`."""
    return meter.create_histogram(REQUEST_LATENCY, description="HTTP request latency in ms")


def fact_processing_latency(meter: Meter) -> Histogram:
    """Fact consumers: milliseconds per fact, attribute `consumer`."""
    return meter.create_histogram(FACT_PROCESSING_LATENCY, description="Fact processing in ms")


def saga_completion(meter: Meter) -> Histogram:
    """Orders: milliseconds from order date to saga close, attribute `outcome`."""
    return meter.create_histogram(SAGA_COMPLETION, description="Order date to saga close in ms")


def outbox_lag(meter: Meter) -> Gauge:
    """Relay services: age in ms of the oldest unpublished outbox row (0 when none)."""
    return meter.create_gauge(OUTBOX_LAG, description="Age of the oldest unpublished row in ms")


def dlq_depth(meter: Meter) -> Gauge:
    """Orders: records on a dead-letter topic, attribute `topic`."""
    return meter.create_gauge(DLQ_DEPTH, description="Dead-letter records per topic")


class FactLatencyHistogram:
    """`FactRetry`'s `FactLatency` port over the fact-processing histogram: one record per fact,
    attribute `consumer` (the `ConsumerName` token). The port is structural, so no import of it."""

    def __init__(self, histogram: Histogram) -> None:
        self._histogram = histogram

    def record(self, milliseconds: float, consumer: str) -> None:
        self._histogram.record(milliseconds, {"consumer": consumer})


class SagaCompletionHistogram:
    """`SagaMetrics` over the saga-completion histogram: one record per closed saga, attribute
    `outcome` (`completed` or `cancelled`). The port is structural, so no import of it."""

    def __init__(self, histogram: Histogram) -> None:
        self._histogram = histogram

    def closed(self, outcome: str, milliseconds: float) -> None:
        self._histogram.record(milliseconds, {"outcome": outcome})
