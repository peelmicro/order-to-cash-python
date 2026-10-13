# ruff: noqa: E501 - test names are claims, spelled out in full
"""R59 / OR9 (S5.3): `otc_request_latency_ms` as the Gateway's `TelemetryMiddleware` records it.

Through the REAL application and middleware stack (the `harness` fixture) with the runtime's meter
replaced by one over an in-memory reader that THIS test owns, so what is read is what the requests
produced. `[MEASURE]`: `scope["route"]` IS visible in the outer middleware after the inner call
(Starlette 1.7.0 / FastAPI): the templated `endpoint` values below could not be produced otherwise.
"""

import dataclasses
from typing import Any
from uuid import uuid4

from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader

from otc_gateway.infrastructure.observability.telemetry import build_telemetry


def _observe(harness: Any) -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    harness.runtime = dataclasses.replace(
        harness.runtime, telemetry=build_telemetry("gateway", "", metric_readers=[reader])
    )
    harness.app.state.runtime = harness.runtime
    return reader


def _by_endpoint(reader: InMemoryMetricReader) -> dict[str, HistogramDataPoint]:
    data = reader.get_metrics_data()
    assert data is not None, "the runtime's meter exported nothing"
    found: dict[str, HistogramDataPoint] = {}
    for resource_metrics in data.resource_metrics:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                assert metric.name == "otc_request_latency_ms"
                for point in metric.data.data_points:
                    assert isinstance(point, HistogramDataPoint)
                    found[str((point.attributes or {})["endpoint"])] = point
    return found


async def test_r59_a_success_an_error_and_an_unmatched_path_are_each_recorded_under_the_route_template(
    harness: Any,
) -> None:
    reader = _observe(harness)
    headers = harness.bearer()

    ok = await harness.client.get("/orders", headers=headers)
    missing = await harness.client.get(f"/orders/{uuid4()}", headers=headers)
    unmatched = await harness.client.get("/no/such/path", headers=headers)

    assert (ok.status_code, missing.status_code) == (200, 404)
    assert unmatched.status_code == 404
    points = _by_endpoint(reader)
    assert set(points) == {"GET /orders", "GET /orders/{id}", "unmatched"}, (
        f"endpoint values were {sorted(points)}"
    )
    assert all(point.count == 1 for point in points.values())
    assert all(point.sum >= 0.0 for point in points.values())


async def test_r59_a_failure_that_becomes_a_500_problem_is_recorded_too(harness: Any) -> None:
    reader = _observe(harness)

    async def explode(order_id: Any) -> None:
        raise RuntimeError("read model down")

    harness.read_model.find_by_id = explode
    response = await harness.client.get(f"/orders/{uuid4()}", headers=harness.bearer())

    assert response.status_code == 500
    points = _by_endpoint(reader)
    assert set(points) == {"GET /orders/{id}"}, f"the error path recorded {sorted(points)}"
    assert points["GET /orders/{id}"].count == 1


async def test_r59_two_requests_with_different_ids_to_one_route_are_one_endpoint_value_with_two_samples(
    harness: Any,
) -> None:
    reader = _observe(harness)
    headers = harness.bearer()

    await harness.client.get(f"/orders/{uuid4()}", headers=headers)
    await harness.client.get(f"/orders/{uuid4()}", headers=headers)

    points = _by_endpoint(reader)
    assert set(points) == {"GET /orders/{id}"}, (
        f"a raw path leaked into the label: {sorted(points)}"
    )
    assert points["GET /orders/{id}"].count == 2


async def test_r59_a_health_probe_is_not_measured(harness: Any) -> None:
    reader = _observe(harness)

    await harness.client.get("/health/live")

    assert reader.get_metrics_data() is None or _by_endpoint(reader) == {}
