"""R56 / R57 / OR4 carrier cases (feature 27 `design.md` 4.3, 12; S3.4): the one carrier module.

The cases ported from #8's carrier tests, plus two of this port's own (a header is never produced
without a span; a child of a restored context mints a NEW span id under the SAME trace id). The
spans come from a provider the test builds and never registers globally.
"""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanContext

from otc_orders.infrastructure.observability.trace_context import (
    context_from_traceparent,
    current_traceparent,
    extract_kafka,
    extract_nats,
    inject_nats,
    kafka_trace_headers,
)

TRACE_ID = 0x4BF92F3577B34DA6A3CE929D0E0E4736
SPAN_ID = 0x00F067AA0BA902B7
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def tracer() -> trace.Tracer:
    return TracerProvider().get_tracer("test_trace_context")


def traceparent_of(context: SpanContext) -> str:
    """The W3C text of a span context, flags included (this SDK also sets the random-id bit: 03)."""
    return f"00-{context.trace_id:032x}-{context.span_id:016x}-{int(context.trace_flags):02x}"


def test_or4_there_is_no_traceparent_without_a_span() -> None:
    assert current_traceparent() is None
    headers: dict[str, str] = {}
    inject_nats(headers)
    assert headers == {}
    assert kafka_trace_headers() == ()


def test_r56_the_current_traceparent_is_the_active_spans() -> None:
    with tracer().start_as_current_span("active") as span:
        context = span.get_span_context()
        value = current_traceparent()

    assert value == traceparent_of(context)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "garbage",
        "00-xyz-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
    ],
)
def test_r56_a_missing_empty_or_malformed_stored_traceparent_restores_nothing(
    value: str | None,
) -> None:
    assert context_from_traceparent(value) is None


def test_r56_a_stored_traceparent_restores_the_same_trace_id() -> None:
    restored = context_from_traceparent(TRACEPARENT)

    assert restored is not None
    context = trace.get_current_span(restored).get_span_context()
    assert (context.trace_id, context.span_id) == (TRACE_ID, SPAN_ID)


def test_r57_a_child_of_a_restored_context_keeps_the_trace_id_and_mints_a_fresh_span_id() -> None:
    restored = context_from_traceparent(TRACEPARENT)
    assert restored is not None

    with tracer().start_as_current_span("child", context=restored) as child:
        context = child.get_span_context()

    assert context.trace_id == TRACE_ID
    assert context.span_id != SPAN_ID


def test_r56_nats_inject_writes_the_active_spans_context_into_a_fresh_dict() -> None:
    headers: dict[str, str] = {}
    with tracer().start_as_current_span("active") as span:
        inject_nats(headers)
        context = span.get_span_context()

    assert headers == {"traceparent": traceparent_of(context)}


def test_r56_nats_inject_takes_an_explicit_context_over_the_active_one() -> None:
    restored = context_from_traceparent(TRACEPARENT)
    assert restored is not None
    headers: dict[str, str] = {}

    with tracer().start_as_current_span("a different active span"):
        inject_nats(headers, restored)

    assert headers == {"traceparent": TRACEPARENT}


def test_r56_nats_extract_round_trips_what_inject_wrote() -> None:
    headers: dict[str, str] = {}
    with tracer().start_as_current_span("origin") as origin:
        inject_nats(headers)
        sent = origin.get_span_context()

    received = trace.get_current_span(extract_nats(headers)).get_span_context()

    assert (received.trace_id, received.span_id) == (sent.trace_id, sent.span_id)


@pytest.mark.parametrize("headers", [None, {}, {"x-other": "1"}, {"traceparent": "garbage"}])
def test_r56_nats_extract_of_missing_or_unrelated_headers_is_an_empty_context(
    headers: dict[str, str] | None,
) -> None:
    assert not trace.get_current_span(extract_nats(headers)).get_span_context().is_valid


def test_r56_kafka_headers_round_trip_through_extract() -> None:
    with tracer().start_as_current_span("origin") as origin:
        pairs = kafka_trace_headers()
        sent = origin.get_span_context()

    assert [name for name, _ in pairs] == ["traceparent"]
    assert all(isinstance(value, bytes) for _, value in pairs)
    received = trace.get_current_span(extract_kafka(pairs)).get_span_context()
    assert (received.trace_id, received.span_id) == (sent.trace_id, sent.span_id)


@pytest.mark.parametrize(
    "headers",
    [None, (), (("event-type", b"x"),), (("traceparent", b"\xff\xfe"),), (("traceparent", b"x"),)],
)
def test_r56_kafka_extract_of_missing_or_unreadable_headers_is_an_empty_context(
    headers: tuple[tuple[str, bytes], ...] | None,
) -> None:
    assert not trace.get_current_span(extract_kafka(headers)).get_span_context().is_valid


def test_r56_kafka_extract_reads_the_header_name_case_insensitively() -> None:
    received = trace.get_current_span(
        extract_kafka((("TraceParent", TRACEPARENT.encode("ascii")),))
    ).get_span_context()

    assert received.trace_id == TRACE_ID
