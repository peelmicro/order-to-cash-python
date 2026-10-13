# ruff: noqa: E501 - test names are claims, spelled out in full
"""R59 / OR9 (S5.8): the series Prometheus STORES are the series the dashboards QUERY.

#8's id 109: no test tied an instrument's name to a dashboard query, and a `unit="ms"` renames the
stored series (`otc_request_latency_ms_milliseconds_bucket`). Here nothing is retyped: the
collector image is BUILT from `infra/otel-collector/` and runs with the repository's own
`otel-collector-config.yaml`; a Prometheus (`prom/prometheus:v3.14.0`) runs with the repository's own
`prometheus.yml`, on a private Docker network where the collector answers to `otel-collector`; each
recording service exports through its OWN `build_telemetry` and its OWN `metrics.py` over OTLP/HTTP;
and the names the test asserts are PARSED from `infra/grafana/dashboards/order-to-cash-overview.json`.

Who records what (each service's own copy of `metrics.py` is used, so a unit added to one copy is
seen): the Gateway the request latency; Orders the fact latency, the saga completion, the outbox
lag and the dead-letter depth; Fulfillment and Billing the outbox lag; the Projector and
Notifications the fact latency. The test is synchronous: testcontainers is, and the OTLP exporter
and Prometheus' scrape (15 s, the repository's interval) are the clocks being waited on.
"""

import importlib
import json
import re
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.metrics import Meter
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPO_ROOT / "infra/grafana/dashboards/order-to-cash-overview.json"
COLLECTOR_DIR = REPO_ROOT / "infra/otel-collector"
PROMETHEUS_CONFIG = REPO_ROOT / "infra/prometheus/prometheus.yml"
PROMETHEUS_IMAGE = "prom/prometheus:v3.14.0"
SCRAPE_SECONDS = 15
FIVE = {
    "otc_request_latency_ms",
    "otc_fact_processing_latency_ms",
    "otc_saga_completion_ms",
    "otc_outbox_lag_ms",
    "otc_dlq_depth",
}
# series name (as the dashboard queries it) -> who must have exported it (`exported_job`)
EXPORTED_BY = {
    "otc_request_latency_ms": {"gateway"},
    "otc_fact_processing_latency_ms": {"orders", "projector", "notifications"},
    "otc_saga_completion_ms": {"orders"},
    "otc_outbox_lag_ms": {"orders", "fulfillment", "billing"},
    "otc_dlq_depth": {"orders"},
}


def dashboard_queries() -> list[str]:
    document = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    return [
        str(target["expr"])
        for panel in document["panels"]
        for target in panel.get("targets", [])
        if "otc_" in str(target.get("expr", ""))
    ]


def queried_series(queries: list[str]) -> set[str]:
    """Every `otc_*` identifier a dashboard query reads, exactly as written."""
    return {name for query in queries for name in re.findall(r"\botc_[a-z0-9_]+\b", query)}


def grouping_keys(queries: list[str]) -> dict[str, set[str]]:
    """series -> the label names the dashboard groups it by (`by (le, exported_job, endpoint)`),
    minus `le`, which a histogram bucket always has."""
    keys: dict[str, set[str]] = {}
    for query in queries:
        grouped = re.search(r"\bby\s*\(([^)]*)\)", query)
        labels = (
            {label.strip() for label in grouped.group(1).split(",")} - {"le"} if grouped else set()
        )
        for name in re.findall(r"\botc_[a-z0-9_]+\b", query):
            keys.setdefault(name, set()).update(labels)
    return keys


def record_each_service_in_its_own_runtime(collector_base: str) -> None:
    """Export the instruments each service records, through that service's own modules."""

    def modules(service: str) -> tuple[Any, Any]:
        base = f"otc_{service}.infrastructure.observability"
        return (
            importlib.import_module(f"{base}.telemetry"),
            importlib.import_module(f"{base}.metrics"),
        )

    def gateway(meter: Meter, m: Any) -> None:
        m.request_latency(meter).record(12.5, {"endpoint": "GET /orders"})

    def orders(meter: Meter, m: Any) -> None:
        m.fact_processing_latency(meter).record(7.25, {"consumer": "orders.saga"})
        m.saga_completion(meter).record(5400123.0, {"outcome": "completed"})
        m.outbox_lag(meter).set(7123.0)
        m.dlq_depth(meter).set(4.0, {"topic": "otc.orders.facts.v1.dlq"})

    def fulfillment(meter: Meter, m: Any) -> None:
        m.outbox_lag(meter).set(3.0)

    def billing(meter: Meter, m: Any) -> None:
        m.outbox_lag(meter).set(5.0)

    def projector(meter: Meter, m: Any) -> None:
        m.fact_processing_latency(meter).record(9.5, {"consumer": "projector"})

    def notifications(meter: Meter, m: Any) -> None:
        m.fact_processing_latency(meter).record(11.5, {"consumer": "notifications"})

    plan: dict[str, Callable[[Meter, Any], None]] = {
        "gateway": gateway,
        "orders": orders,
        "fulfillment": fulfillment,
        "billing": billing,
        "projector": projector,
        "notifications": notifications,
    }
    assert set(plan) == {
        "gateway",
        "orders",
        "fulfillment",
        "billing",
        "projector",
        "notifications",
    }
    for service, record in plan.items():
        telemetry_module, metrics_module = modules(service)
        telemetry = telemetry_module.build_telemetry(service, collector_base)
        record(telemetry.meter, metrics_module)
        telemetry.shutdown()  # force_flush + shutdown: the reader's final export is OTLP/HTTP


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - a container on localhost
        return json.loads(response.read())


@pytest.fixture(scope="module")
def prometheus_with_collector() -> Iterator[tuple[str, str]]:
    """(collector OTLP base URL, Prometheus base URL) on a private network."""
    # A host credential helper for an unrelated registry must not be able to fail the build; the
    # base image is pulled anonymously. DockerImage builds its Docker client from the environment,
    # so DOCKER_CONFIG must point at an empty config before it is constructed, with an empty
    # config.json, since docker-py falls back to ~/.docker/config.json when the directory has none.
    with (
        pytest.MonkeyPatch.context() as env,
        tempfile.TemporaryDirectory() as empty_docker_config,
    ):
        env.setenv("DOCKER_CONFIG", empty_docker_config)
        (Path(empty_docker_config) / "config.json").write_text("{}", encoding="utf-8")
        with (
            Network() as network,
            DockerImage(path=str(COLLECTOR_DIR), tag="otc9-series-names-collector:test") as image,
            DockerContainer(str(image.tag))
            .with_network(network)
            .with_network_aliases("otel-collector")
            .with_exposed_ports(4318)
            .with_volume_mapping(
                str(COLLECTOR_DIR / "otel-collector-config.yaml"),
                "/etc/otelcol-contrib/config.yaml",
                "ro",
            ) as collector,
            DockerContainer(PROMETHEUS_IMAGE)
            .with_network(network)
            .with_exposed_ports(9090)
            .with_volume_mapping(
                str(PROMETHEUS_CONFIG), "/etc/prometheus/prometheus.yml", "ro"
            ) as prometheus,
        ):
            LogMessageWaitStrategy("Everything is ready").with_startup_timeout(90).wait_until_ready(
                collector
            )
            LogMessageWaitStrategy("Server is ready to receive web requests").with_startup_timeout(
                90
            ).wait_until_ready(prometheus)
            yield (
                f"http://{collector.get_container_host_ip()}:{collector.get_exposed_port(4318)}",
                f"http://{prometheus.get_container_host_ip()}:{prometheus.get_exposed_port(9090)}",
            )


def stored_series(prometheus_url: str) -> dict[str, list[dict[str, str]]]:
    query = urllib.parse.urlencode({"match[]": '{__name__=~"otc_.*"}'})
    answer = get_json(f"{prometheus_url}/api/v1/series?{query}")
    found: dict[str, list[dict[str, str]]] = {}
    for labels in answer["data"]:
        found.setdefault(labels["__name__"], []).append(labels)
    return found


def test_or9_the_five_series_prometheus_stores_are_the_dashboards(
    prometheus_with_collector: tuple[str, str],
) -> None:
    collector_url, prometheus_url = prometheus_with_collector
    queries = dashboard_queries()
    queried = queried_series(queries)
    grouped = grouping_keys(queries)
    # The dashboard queries exactly the five names (the histograms through `_bucket`), nothing else:
    assert {name.removesuffix("_bucket") for name in queried} == FIVE, sorted(queried)

    record_each_service_in_its_own_runtime(collector_url)

    deadline = time.monotonic() + 3 * SCRAPE_SECONDS + 30
    stored: dict[str, list[dict[str, str]]] = {}
    while time.monotonic() < deadline:
        stored = stored_series(prometheus_url)
        if queried <= set(stored):
            break
        time.sleep(3)
    missing = sorted(queried - set(stored))
    assert not missing, (
        f"the dashboards query series Prometheus does not store: {missing}; it stores {sorted(stored)}"
    )

    for name in sorted(queried):
        series = stored[name]
        base = name.removesuffix("_bucket")
        jobs = {labels.get("exported_job") for labels in series}
        assert jobs == EXPORTED_BY[base], f"{name}: exported_job values {sorted(map(str, jobs))}"
        for key in grouped[name]:
            assert all(key in labels for labels in series), (
                f"{name}: the dashboard groups by {key!r}, a stored series lacks it: {series}"
            )
    assert {labels["topic"] for labels in stored["otc_dlq_depth"]} == {"otc.orders.facts.v1.dlq"}
    assert {labels["outcome"] for labels in stored["otc_saga_completion_ms_bucket"]} == {
        "completed"
    }
    assert not [name for name in stored if "milliseconds" in name], (
        f"an instrument declares a unit: {sorted(stored)}"
    )


def test_or9_every_instrument_is_created_through_the_metrics_module_of_its_service() -> None:
    """The plan above exports through each service's own `metrics.py`; a service the plan does not
    cover would be a recording service this test never sees."""
    for service in ("gateway", "orders", "fulfillment", "billing", "projector", "notifications"):
        module = importlib.import_module(f"otc_{service}.infrastructure.observability.metrics")
        assert {
            module.REQUEST_LATENCY,
            module.FACT_PROCESSING_LATENCY,
            module.SAGA_COMPLETION,
            module.OUTBOX_LAG,
            module.DLQ_DEPTH,
        } == FIVE, service
