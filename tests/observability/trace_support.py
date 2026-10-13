"""Typed readers over exported spans, shared by the tracing tests of feature 27 (S3).

Not a test module. Loaded BY PATH (the suite runs in importlib mode, so a sibling module is not
importable by name), the way `log_contract_support.py` is. It imports nothing from a service: a test
builds its runtime's providers with the service's own `build_telemetry(..., span_processors=[...])`
and hands the processor made here.

`InMemorySpanExporter().get_finished_spans()[0].context` reveals `Any` under `mypy --strict`
(measured in S0, design 4.1): every test reads spans through `span_infos` so the `Any` stops here.
"""

import asyncio
from typing import Any, NamedTuple

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


class SpanInfo(NamedTuple):
    name: str
    kind: SpanKind
    trace_id: int
    span_id: int
    parent_id: int | None
    service: str
    attributes: dict[str, Any]


def new_recorder() -> tuple[InMemorySpanExporter, SimpleSpanProcessor]:
    """A fresh exporter and the synchronous processor that feeds it (finished spans are visible at
    once, no flush needed)."""
    exporter = InMemorySpanExporter()
    return exporter, SimpleSpanProcessor(exporter)


def info_of(span: ReadableSpan) -> SpanInfo:
    context: Any = span.context
    parent: Any = span.parent
    resource: Any = span.resource
    return SpanInfo(
        name=span.name,
        kind=span.kind,
        trace_id=int(context.trace_id),
        span_id=int(context.span_id),
        parent_id=None if parent is None else int(parent.span_id),
        service=str(resource.attributes.get("service.name")),
        attributes=dict(span.attributes or {}),
    )


def span_infos(exporter: InMemorySpanExporter) -> list[SpanInfo]:
    return [info_of(span) for span in exporter.get_finished_spans()]


def trace_hex(trace_id: int) -> str:
    return format(trace_id, "032x")


def span_hex(span_id: int) -> str:
    return format(span_id, "016x")


def caller_tracer() -> Tracer:
    """A tracer of the TEST's own provider, standing for the caller (the Gateway, an upstream
    service): spans made with it are never exported by the runtime under test."""
    return TracerProvider().get_tracer("test-caller")


def traceparent_header_of_current_span() -> dict[str, str]:
    """The NATS headers a caller inside the current span would send (the W3C text, built here with
    the library's own propagator, independent of the module under test)."""
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier


def by_name(infos: list[SpanInfo], name: str) -> list[SpanInfo]:
    return [info for info in infos if info.name == name]


class HoldingConnection:
    """Wraps a real nats-py client. The FIRST request to reach `request` is held there until a
    SECOND has arrived, so two concurrent calls overlap inside the adapter under test: the second
    has built its headers while the first is still between "headers built" and "headers sent". The
    overlap is created by the test, never left to scheduling (ledger L23). It adds no delay of any
    other kind: a mutation that shares one headers dict between calls fails because of the overlap
    alone."""

    def __init__(self, inner: Any, *, expected: int = 2) -> None:
        self._inner = inner
        self._expected = expected
        self._arrived = 0
        self._together = asyncio.Event()

    async def request(
        self,
        subject: str,
        payload: bytes = b"",
        *,
        timeout: float = 0.5,  # noqa: ASYNC109 - nats-py's own request parameter
        headers: dict[str, str] | None = None,
    ) -> Any:
        self._arrived += 1
        if self._arrived >= self._expected:
            self._together.set()
        async with asyncio.timeout(10):
            await self._together.wait()
        return await self._inner.request(subject, payload, timeout=timeout, headers=headers)


class Receiver:
    """A NATS subscriber that records (subject, body, headers) of every request it gets and answers
    each with `reply`."""

    def __init__(self, client: Any, reply: bytes) -> None:
        self._client = client
        self._reply = reply
        self.received: list[tuple[str, bytes, dict[str, str] | None]] = []

    @classmethod
    async def start(cls, url: str, subjects: list[str], reply: bytes) -> Receiver:
        import nats

        receiver = cls(await nats.connect(url), reply)
        for subject in subjects:
            await receiver._client.subscribe(subject, cb=receiver._on_request)
        await receiver._client.flush()
        return receiver

    async def _on_request(self, message: Any) -> None:
        headers = None if message.headers is None else dict(message.headers)
        self.received.append((message.subject, bytes(message.data), headers))
        await message.respond(self._reply)

    async def close(self) -> None:
        await self._client.close()


def trace_id_of_header(headers: dict[str, str] | None) -> int:
    """The trace id a request's `traceparent` header carries (0 when it carries none)."""
    if not headers or "traceparent" not in headers:
        return 0
    return int(headers["traceparent"].split("-")[1], 16)
