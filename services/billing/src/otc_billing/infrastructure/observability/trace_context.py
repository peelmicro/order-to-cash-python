"""The one trace-context carrier module (`R56`, `R57`, `OR4`; the spec's `design.md` 4.3).

Copy of `services/orders/src/otc_orders/infrastructure/observability/trace_context.py`.

The canonical is Orders'; `tests/architecture/test_observability_copy_parity.py` fails
on any difference after this docstring. Edit the canonical, then copy.
"""

from collections.abc import Mapping, Sequence

from opentelemetry import trace
from opentelemetry.context import Context, get_current
from opentelemetry.trace import Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

TRACEPARENT: str = "traceparent"
_PROPAGATOR = TraceContextTextMapPropagator()

# The tracer a component holds until the composition root hands it the runtime's own: it makes no
# span, so a unit test that builds a component directly needs no provider and produces no header.
NO_TRACER: Tracer = trace.NoOpTracer()

# The name of the span around each write-model transaction (`R56`): the server span's child and the
# parent of every outbox row the transaction writes, so the relay's producer span chains to it.
TRANSACTION_SPAN: str = "writemodel.transaction"


def _valid(context: Context) -> bool:
    return trace.get_current_span(context).get_span_context().is_valid


def inject_nats(headers: dict[str, str], context: Context | None = None) -> None:
    """Write `traceparent` (and `tracestate` when the span carries one) into `headers`. `context`
    defaults to the CURRENT one; nothing is written when it holds no valid span."""
    _PROPAGATOR.inject(headers, context=get_current() if context is None else context)


def extract_nats(headers: Mapping[str, str] | None) -> Context:
    """The context carried by NATS headers; an empty context when absent or malformed."""
    if not headers:
        return Context()
    return _PROPAGATOR.extract(headers, context=Context())


def kafka_trace_headers(context: Context | None = None) -> tuple[tuple[str, bytes], ...]:
    """The trace headers of `context` (default: the current one) as Kafka header pairs."""
    carrier: dict[str, str] = {}
    inject_nats(carrier, context)
    return tuple((name, value.encode("ascii")) for name, value in carrier.items())


def extract_kafka(headers: Sequence[tuple[str, bytes]] | None) -> Context:
    """The context carried by Kafka headers; an empty context when absent or malformed."""
    if not headers:
        return Context()
    carrier: dict[str, str] = {}
    for name, value in headers:
        try:
            carrier[name.lower()] = value.decode("ascii")
        except UnicodeDecodeError:
            continue
    return _PROPAGATOR.extract(carrier, context=Context())


def current_traceparent() -> str | None:
    """The `traceparent` of the span active in the calling context; `None` with none (`OR4`)."""
    carrier: dict[str, str] = {}
    inject_nats(carrier)
    return carrier.get(TRACEPARENT)


def context_from_traceparent(value: str | None) -> Context | None:
    """The context a stored `traceparent` restores; `None` for `None`, empty or malformed text."""
    if not value:
        return None
    context = _PROPAGATOR.extract({TRACEPARENT: value}, context=Context())
    return context if _valid(context) else None
