"""R59 / OR9 (S5.1): the five instruments exist under the dashboards' names, of the right kind, with
NO unit (a unit renames the stored series, `design.md` 6.1)."""

from collections.abc import Callable

from opentelemetry.metrics import Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from otc_orders.infrastructure.observability import metrics
from otc_orders.infrastructure.observability.metrics import Gauge

EXPECTED: dict[str, tuple[str, Callable[[Meter], Histogram | Gauge]]] = {
    "otc_request_latency_ms": ("histogram", metrics.request_latency),
    "otc_fact_processing_latency_ms": ("histogram", metrics.fact_processing_latency),
    "otc_saga_completion_ms": ("histogram", metrics.saga_completion),
    "otc_outbox_lag_ms": ("gauge", metrics.outbox_lag),
    "otc_dlq_depth": ("gauge", metrics.dlq_depth),
}


def _collected() -> dict[str, tuple[str, str]]:
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("test")
    for _kind, factory in EXPECTED.values():
        instrument = factory(meter)
        if isinstance(instrument, Histogram):
            instrument.record(1.0, {"k": "v"})
        else:
            instrument.set(1.0, {"k": "v"})
    data = reader.get_metrics_data()
    assert data is not None
    found: dict[str, tuple[str, str]] = {}
    for resource_metrics in data.resource_metrics:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                found[metric.name] = (type(metric.data).__name__.lower(), metric.unit or "")
    return found


def test_r59_the_five_instruments_have_the_dashboard_names_their_kind_and_an_empty_unit() -> None:
    found = _collected()
    assert set(found) == set(EXPECTED), f"instrument names differ: {sorted(found)}"
    for name, (kind, _factory) in EXPECTED.items():
        assert found[name] == (kind, ""), (
            f"{name}: expected kind {kind} and no unit, got {found[name]}"
        )


def test_r59_the_name_constants_are_the_five_names_the_dashboards_query() -> None:
    assert tuple(EXPECTED) == metrics.METRIC_NAMES
