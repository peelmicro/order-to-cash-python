"""R56 / R57 mechanism: a runtime's providers are its own (feature 27 `design.md` 4.2; S3.2).

* (a) two runtimes built in one process export to their OWN exporters under their OWN
  `service.name`, and neither is registered as the process-global provider;
* (b) the four environment variables the SDK would read on its own (`OTEL_SERVICE_NAME`,
  `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_TRACES_SAMPLER`, `OTEL_PROPAGATORS`) change nothing. This one
  runs in a FRESH interpreter: `opentelemetry.propagate` reads `OTEL_PROPAGATORS` once, at import,
  so only a process that imports it after the variables are set can see that read;
* (c) a configured base URL becomes `<base>/v1/traces` and `<base>/v1/metrics` (an explicit
  endpoint is used verbatim by the exporter): proven against a real local HTTP listener, and an
  empty base opens no exporter, so nothing is sent.
"""

import http.server
import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider

import otc_orders.infrastructure.observability.telemetry as telemetry_module
from otc_orders.infrastructure.observability.telemetry import build_telemetry

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/trace_support.py"


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trace_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()


def test_r56_two_runtimes_in_one_process_export_to_their_own_exporters_under_their_own_name() -> (
    None
):
    orders_exporter, orders_processor = support.new_recorder()
    gateway_exporter, gateway_processor = support.new_recorder()
    orders = build_telemetry("orders", "", span_processors=[orders_processor])
    gateway = build_telemetry("gateway", "", span_processors=[gateway_processor])

    with orders.tracer.start_as_current_span("orders-span"):
        pass
    with gateway.tracer.start_as_current_span("gateway-span"):
        pass

    assert [(i.name, i.service) for i in support.span_infos(orders_exporter)] == [
        ("orders-span", "orders")
    ]
    assert [(i.name, i.service) for i in support.span_infos(gateway_exporter)] == [
        ("gateway-span", "gateway")
    ]
    # no runtime's provider became the process-global one (set-once per process). The check is on
    # the TYPE: an `is not` against these two providers passes whenever an EARLIER runtime in the
    # same pytest process was the one that set the global (S8a, L9: the meter half had no arm)
    assert not isinstance(trace.get_tracer_provider(), SdkTracerProvider)
    assert not isinstance(metrics.get_meter_provider(), SdkMeterProvider)
    orders.shutdown()
    gateway.shutdown()


CHILD = """
import json
from opentelemetry import trace
from otc_orders.infrastructure.observability.telemetry import build_telemetry
from otc_orders.infrastructure.observability.trace_context import inject_nats
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
telemetry = build_telemetry("orders", "", span_processors=[SimpleSpanProcessor(exporter)])
headers = {}
with telemetry.tracer.start_as_current_span("probe") as span:
    inject_nats(headers)
    sampled = span.get_span_context().trace_flags.sampled
finished = exporter.get_finished_spans()
print(json.dumps({
    "sampled": bool(sampled),
    "exported": len(finished),
    "resource": dict(finished[0].resource.attributes) if finished else None,
    "header_names": sorted(headers),
}))
"""


def test_r56_the_environment_cannot_rename_the_service_unsample_it_or_change_its_propagator() -> (
    None
):
    import os

    env = {
        **os.environ,
        "OTEL_SERVICE_NAME": "wrong",
        "OTEL_RESOURCE_ATTRIBUTES": "service.name=wrong,deployment.environment=wrong",
        "OTEL_TRACES_SAMPLER": "always_off",
        "OTEL_PROPAGATORS": "baggage",  # b3 is not installed: it would fail the import itself
    }
    result = subprocess.run(  # noqa: S603 - the interpreter running this suite, a fixed script
        [sys.executable, "-I", "-c", CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    reported = json.loads(result.stdout.splitlines()[-1])
    assert reported == {
        "sampled": True,
        "exported": 1,
        "resource": {"service.name": "orders"},
        "header_names": ["traceparent"],
    }


class _Collector(http.server.BaseHTTPRequestHandler):
    paths: list[str]

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        type(self).paths.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def _listener() -> tuple[http.server.HTTPServer, list[str]]:
    paths: list[str] = []
    handler = type("Collector", (_Collector,), {"paths": paths})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, paths


def test_r56_a_base_url_becomes_the_v1_traces_and_v1_metrics_endpoints() -> None:
    server, paths = _listener()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        telemetry = build_telemetry("orders", base + "/")
        with telemetry.tracer.start_as_current_span("exported"):
            pass
        telemetry.meter.create_counter("probe_total").add(1)
        telemetry.shutdown()
    finally:
        server.shutdown()
        server.server_close()

    assert sorted(set(paths)) == ["/v1/metrics", "/v1/traces"]


def test_or4_an_empty_base_url_constructs_no_exporter_and_a_set_one_constructs_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[tuple[str, str]] = []

    class RecordingSpanExporter(OTLPSpanExporter):
        def __init__(self, *, endpoint: str) -> None:
            built.append(("traces", endpoint))
            super().__init__(endpoint=endpoint)

    class RecordingMetricExporter(OTLPMetricExporter):
        def __init__(self, *, endpoint: str) -> None:
            built.append(("metrics", endpoint))
            super().__init__(endpoint=endpoint)

    monkeypatch.setattr(telemetry_module, "OTLPSpanExporter", RecordingSpanExporter)
    monkeypatch.setattr(telemetry_module, "OTLPMetricExporter", RecordingMetricExporter)

    build_telemetry("orders", "").shutdown()
    assert built == [], "an empty OTEL_EXPORTER_OTLP_ENDPOINT must open no exporter"

    build_telemetry("orders", "http://collector.sentinel:4318").shutdown()
    assert built == [
        ("traces", "http://collector.sentinel:4318/v1/traces"),
        ("metrics", "http://collector.sentinel:4318/v1/metrics"),
    ]
