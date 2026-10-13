# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R58` / `R57` for a record the consumer cannot read (S8a; #8's `LogCorrelationTests`,
`OR4_...TheMalformedEnvelopeLogCarriesTheRealInboundTraceId`).

The malformed-envelope line is written by `SagaFactsConsumerTask.handle` inside the consume span the
subscriber opens from the record's `traceparent`. Nothing else proved that line carries the inbound
trace: the log-contract tests drive an RPC, the dead-letter tests a well-formed envelope. The line
is rendered by the PRODUCTION formatter (`build_formatter`) on a handler of the test's own.
"""

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator
from io import StringIO
from types import ModuleType
from typing import Any

import pytest

from otc_orders.infrastructure.observability.logging import build_formatter

Waits = Callable[..., Awaitable[None]]
FAST = {
    "FACT_RETRY_BACKOFF_MS": "20",
    "OUTBOX_RELAY_ENABLED": "false",
    "SAGA_SWEEPER_ENABLED": "false",
}
CONSUMER_LOGGER = "otc_orders.presentation.saga_facts_consumer"
RETRY_LOGGER = "otc_orders.messaging.fact_retry"
MALFORMED = "malformed fact envelope acknowledged without processing"


@pytest.fixture
def rendered() -> Iterator[StringIO]:
    """The consumer's and the retry wrapper's loggers rendered by the production formatter into a
    buffer of the test's own."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_formatter())
    loggers = [logging.getLogger(name) for name in (CONSUMER_LOGGER, RETRY_LOGGER)]
    previous = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    yield stream
    for logger, level in zip(loggers, previous, strict=True):
        logger.removeHandler(handler)
        logger.setLevel(level)


def malformed_lines(stream: StringIO, length: int) -> list[dict[str, Any]]:
    return [
        document
        for document in (json.loads(line) for line in stream.getvalue().splitlines())
        if document["event"] == MALFORMED and document.get("length") == length
    ]


async def test_r58_the_malformed_envelope_line_carries_the_inbound_trace_id_and_a_record_without_a_traceparent_starts_its_own_root(
    saga_harness: Any,
    private_topics: Any,
    dl_support: ModuleType,
    trace_support: ModuleType,
    kafka_server: Any,
    waits: Waits,
    rendered: StringIO,
) -> None:
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    traced = b'{"this": "is not an envelope", "traced": true}'
    untraced = b'{"this": "is not an envelope either", "untraced": 1, "padding": "x"}'
    assert len(traced) != len(untraced), "the lines are told apart by the length they log"
    with trace_support.caller_tracer().start_as_current_span("fact producer") as origin:
        inbound_trace = trace_support.trace_hex(origin.get_span_context().trace_id)
        inbound = trace_support.traceparent_header_of_current_span()["traceparent"]

    async with saga_harness(topics=private_topics, **FAST):
        await dl_support.produce(
            servers,
            source,
            key=b"k",
            value=traced,
            headers=[("traceparent", inbound.encode("ascii"))],
        )

        async def traced_logged() -> bool:
            return bool(malformed_lines(rendered, len(traced)))

        await waits(traced_logged, "the traced malformed record was logged by the consumer")
        await dl_support.produce(servers, source, key=b"k", value=untraced)

        async def untraced_logged() -> bool:
            return bool(malformed_lines(rendered, len(untraced)))

        await waits(untraced_logged, "the untraced malformed record was logged by the consumer")

    [traced_line] = malformed_lines(rendered, len(traced))
    [untraced_line] = malformed_lines(rendered, len(untraced))
    assert traced_line["traceId"] == inbound_trace, (
        "the malformed line is written inside the consume span, which continues the inbound trace"
    )
    assert len(traced_line["spanId"]) == 16
    assert untraced_line["traceId"] != inbound_trace, (
        "a record with no traceparent starts its own root trace: it never borrows another record's"
    )
    assert untraced_line["traceId"] != traced_line["traceId"]


ATTEMPT_FAILED = "fact processing attempt failed"


async def test_r58_a_line_written_inside_the_consumers_unit_of_work_carries_the_envelopes_correlation_id_and_the_inbound_trace_id(
    saga_harness: Any,
    private_topics: Any,
    dl_support: ModuleType,
    trace_support: ModuleType,
    kafka_server: Any,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
    rendered: StringIO,
) -> None:
    """S1 finding 1: the consumer's binding site (`handle`) was proved by the census only, because
    the log-contract tests drive an RPC. `FactRetry`'s per-attempt WARNING is written with NO
    `correlationId` argument, so only `bound_contextvars` can put it on the line. The poison is a
    well-formed envelope whose payload fails its model, so the failure happens on every attempt."""
    servers, source = kafka_server.bootstrap_servers, private_topics.orders
    correlation = uuid.uuid4()
    produced = make_fact_bytes(
        "order.placed.v1",
        correlation_id=correlation,
        reference="ORD-000101",
        event_id=uuid.uuid4(),
        payload={"orderReference": 42},
    )
    with trace_support.caller_tracer().start_as_current_span("fact producer") as origin:
        inbound_trace = trace_support.trace_hex(origin.get_span_context().trace_id)
        inbound = trace_support.traceparent_header_of_current_span()["traceparent"]

    async with saga_harness(topics=private_topics, **FAST):
        await dl_support.produce(
            servers,
            source,
            key=str(correlation).encode(),
            value=produced,
            headers=[("traceparent", inbound.encode("ascii"))],
        )

        async def three_attempts() -> bool:
            return len(lines_of(rendered, ATTEMPT_FAILED)) == 3

        await waits(three_attempts, "the retry wrapper logged the poison's three failed attempts")

    attempts = lines_of(rendered, ATTEMPT_FAILED)
    assert [line.get("correlationId") for line in attempts] == [str(correlation)] * 3, (
        "the consumer's binding put the envelope's correlation id on lines that name none"
    )
    assert {line.get("traceId") for line in attempts} == {inbound_trace}


def lines_of(stream: StringIO, event: str) -> list[dict[str, Any]]:
    return [
        document
        for document in (json.loads(line) for line in stream.getvalue().splitlines())
        if document["event"] == event
    ]
