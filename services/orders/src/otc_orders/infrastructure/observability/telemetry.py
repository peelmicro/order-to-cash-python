"""The runtime's own tracer and meter providers (`R56`, `R59`; the spec's `design.md` 4.2).

Providers belong to the lifespan, never to the process. `build_telemetry` constructs ONE
`TracerProvider` and ONE `MeterProvider` per runtime and NEVER calls `trace.set_tracer_provider` or
`metrics.set_meter_provider`: both are set-once per process ("Overriding of current TracerProvider
is not allowed"), and one pytest process boots many runtimes (several tests boot Orders, the
Projector and the Gateway together), so a global provider would give every later runtime the first
one's exporter and `service.name`. A component that makes a span or a measurement receives its
`Tracer` / instrument from the runtime through the composition root.

Four environment reads the OpenTelemetry SDK would make on its own are closed here, each by
constructing the thing explicitly (the environment is read through pydantic-settings only):
`Resource({...})`, never `Resource.create(...)` (its detectors read `OTEL_SERVICE_NAME` and
`OTEL_RESOURCE_ATTRIBUTES`); an explicit `ParentBased(ALWAYS_ON)` sampler (`OTEL_TRACES_SAMPLER` is
not read); propagation is the explicit `TraceContextTextMapPropagator` of `trace_context.py`, never
`opentelemetry.propagate` (it reads `OTEL_PROPAGATORS` at import).

With `otlp_endpoint` set (a BASE URL) a `BatchSpanProcessor` over `OTLPSpanExporter` and a
`PeriodicExportingMetricReader` over `OTLPMetricExporter` are added; an explicit endpoint is used
VERBATIM, path included, so the paths are appended here. With it empty no exporter exists. A test
passes its own in-memory processors and readers through `span_processors` / `metric_readers`.

`Telemetry.shutdown` flushes and shuts both providers down; the runtime's `stop()` calls it LAST,
after every task that could still make a span has been awaited.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
from opentelemetry.trace import Tracer

TRACES_PATH = "/v1/traces"
METRICS_PATH = "/v1/metrics"


@dataclass(frozen=True, slots=True)
class Telemetry:
    """What one runtime holds: its providers and the tracer and meter taken from them."""

    service: str
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    tracer: Tracer
    meter: Meter

    def shutdown(self) -> None:
        """Flush, then shut down, the tracer provider and the meter provider (idempotent)."""
        self.tracer_provider.force_flush()
        self.tracer_provider.shutdown()
        self.meter_provider.force_flush()
        self.meter_provider.shutdown()

    async def aclose(self) -> None:
        """`shutdown` off the event loop: the OTLP exporters flush over blocking HTTP, which would
        otherwise hold every other task of the runtime (a collector that is down costs seconds)."""
        await asyncio.to_thread(self.shutdown)


def endpoint_of(base: str, path: str) -> str:
    """The exporter's endpoint from the configured base URL (one trailing slash tolerated)."""
    return f"{base.rstrip('/')}{path}"


def build_telemetry(
    service: str,
    otlp_endpoint: str,
    *,
    span_processors: Sequence[SpanProcessor] = (),
    metric_readers: Sequence[MetricReader] = (),
) -> Telemetry:
    """Build one runtime's providers. `service` is the `service.name` resource attribute."""
    resource = Resource({"service.name": service})
    tracer_provider = TracerProvider(sampler=ParentBased(ALWAYS_ON), resource=resource)
    readers: list[MetricReader] = list(metric_readers)
    if otlp_endpoint:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint_of(otlp_endpoint, TRACES_PATH)))
        )
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint_of(otlp_endpoint, METRICS_PATH))
            )
        )
    for processor in span_processors:
        tracer_provider.add_span_processor(processor)
    meter_provider = MeterProvider(metric_readers=readers, resource=resource)
    return Telemetry(
        service=service,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        tracer=tracer_provider.get_tracer(f"otc_{service}"),
        meter=meter_provider.get_meter(f"otc_{service}"),
    )
