"""R56: all fifteen RPC subjects pass through their responder's one extraction site (feature 27
`design.md` 4.4; S3.6).

The three responder classes (Orders 3 subjects, Fulfillment 6, Billing 6) each serve a request in
ONE method, `_serve`, which extracts the caller's `traceparent` and starts the `SERVER` span. This
test drives the PRODUCTION classes: `start()` subscribes against a recording connection (so the
subjects are what each class REALLY subscribes, not what a table says), then a request for every
subscribed subject is delivered through the callback `start()` registered, `run()` serves it, and
the span the class exported for that subject must be a child of the caller's span. A subject that
bypassed `_serve` would export no span for it; one whose extraction site were missing would export
a root.

The expected subjects are READ from each service's `subjects.py` constants (every `*_SUBJECT`
constant that is a subject the service ANSWERS: Orders' `STOCK_CHECK_SUBJECT` is the outbound call).
The messages carry no reply subject, so `_answer` drops them after logging and nothing below the
extraction site (dispatcher, database) is needed.
"""

import asyncio
import importlib
import importlib.util
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from opentelemetry import trace

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


@dataclass(frozen=True)
class ResponderUnderTest:
    label: str
    service: str
    module: str
    class_name: str
    extra: dict[str, Any]
    outbound: frozenset[str]  # constants of subjects.py that the service CALLS, not answers


RESPONDERS = [
    ResponderUnderTest(
        "orders",
        "otc_orders",
        "presentation.orders_create_responder",
        "OrdersCreateResponder",
        {},
        frozenset({"STOCK_CHECK_SUBJECT"}),
    ),
    ResponderUnderTest(
        "fulfillment",
        "otc_fulfillment",
        "presentation.stock_responder",
        "StockResponder",
        {"max_concurrent_requests": 4},
        frozenset(),
    ),
    ResponderUnderTest(
        "billing",
        "otc_billing",
        "presentation.credit_responder",
        "CreditResponder",
        {"max_concurrent_requests": 4},
        frozenset(),
    ),
]
EXPECTED_TOTAL = 15


class RecordingSubscription:
    async def unsubscribe(self) -> None:
        return None


class RecordingConnection:
    """The slice of nats-py's `Client` a responder's `start()` uses."""

    def __init__(self) -> None:
        self.callbacks: dict[str, Callable[[Any], Awaitable[None]]] = {}

    async def subscribe(
        self, subject: str, *, queue: str, cb: Callable[[Any], Awaitable[None]]
    ) -> RecordingSubscription:
        assert subject not in self.callbacks, f"{subject} subscribed twice"
        self.callbacks[subject] = cb
        return RecordingSubscription()

    async def flush(self) -> None:
        return None


def constants_of(responder: ResponderUnderTest) -> set[str]:
    subjects = importlib.import_module(f"{responder.service}.infrastructure.messaging.subjects")
    return {
        value
        for name, value in vars(subjects).items()
        if name.endswith("_SUBJECT") and isinstance(value, str) and name not in responder.outbound
    }


async def served_spans(responder: ResponderUnderTest) -> tuple[set[str], list[Any], Any]:
    module = importlib.import_module(f"{responder.service}.{responder.module}")
    telemetry_module = importlib.import_module(
        f"{responder.service}.infrastructure.observability.telemetry"
    )
    exporter, processor = support.new_recorder()
    telemetry = telemetry_module.build_telemetry(responder.label, "", span_processors=[processor])
    connection = RecordingConnection()
    instance = getattr(module, responder.class_name)(
        connection=connection,
        dispatcher=None,
        scope_factory=lambda: None,
        clock=None,
        tracer=telemetry.tracer,
        **responder.extra,
    )
    await instance.start()
    with support.caller_tracer().start_as_current_span("caller") as origin:
        caller = origin.get_span_context()
        headers = support.traceparent_header_of_current_span()
    stop = asyncio.Event()
    task = asyncio.create_task(instance.run(stop))
    for callback in connection.callbacks.values():
        await callback(SimpleNamespace(headers=headers, reply="", data=b""))
    async with asyncio.timeout(10):
        while len(exporter.get_finished_spans()) < len(connection.callbacks):  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    stop.set()
    await task
    telemetry.shutdown()
    return set(connection.callbacks), support.span_infos(exporter), caller


@pytest.mark.parametrize("responder", RESPONDERS, ids=lambda r: r.label)
async def test_r56_every_subject_a_responder_subscribes_is_the_subjects_py_constants_and_passes_through_its_extraction_site(  # noqa: E501
    responder: ResponderUnderTest,
) -> None:
    subscribed, infos, caller = await served_spans(responder)

    assert subscribed == constants_of(responder), (
        "the class subscribes other than subjects.py names"
    )
    by_subject = {i.name.removesuffix(" serve"): i for i in infos}
    assert set(by_subject) == subscribed, "a subject was not served through the extraction site"
    for subject, info in by_subject.items():
        assert info.kind == trace.SpanKind.SERVER, subject
        assert (info.trace_id, info.parent_id) == (caller.trace_id, caller.span_id), (
            f"{subject}: the server span does not continue the caller's trace"
        )


async def test_r56_the_three_responder_classes_serve_exactly_fifteen_subjects() -> None:
    total: set[str] = set()
    for responder in RESPONDERS:
        subscribed, _, _ = await served_spans(responder)
        assert total.isdisjoint(subscribed), f"{responder.label} repeats a subject"
        total |= subscribed

    assert len(total) == EXPECTED_TOTAL, sorted(total)
