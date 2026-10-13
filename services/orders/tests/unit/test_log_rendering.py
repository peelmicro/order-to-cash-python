"""R58 / OR7 rendering of one log line (feature 27 `design.md` 2.1, 2.5; S1.3).

Each test installs the canonical formatter on a PRIVATE logger (its own name, `propagate = False`)
writing to a `StringIO`, so nothing here reads or writes pytest's capture handler or the root
logger. The spans come from a provider the test builds and never registers globally.
"""

import json
import logging
from collections.abc import Iterator
from io import StringIO
from typing import Any

import pytest
import structlog
from opentelemetry.sdk.trace import TracerProvider

from otc_orders.infrastructure.observability.logging import build_formatter

FIRST = "5f1d6a4e-0b1c-4a52-9d6f-7a1e2b3c4d5e"
SECOND = "a3c9e7f1-2d4b-4c68-8e0a-91b2c3d4e5f6"


class Sink:
    def __init__(self, logger: logging.Logger, stream: StringIO) -> None:
        self.logger = logger
        self._stream = stream

    @property
    def text(self) -> str:
        return self._stream.getvalue()

    @property
    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.text.splitlines()]


@pytest.fixture
def sink(request: pytest.FixtureRequest) -> Iterator[Sink]:
    structlog.contextvars.clear_contextvars()
    stream = StringIO()
    logger = logging.getLogger(f"otc_orders.test.rendering.{request.node.name}")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_formatter())
    logger.addHandler(handler)
    yield Sink(logger, stream)
    logger.removeHandler(handler)
    structlog.contextvars.clear_contextvars()


def test_r58_a_record_with_no_valid_span_renders_neither_trace_key(sink: Sink) -> None:
    sink.logger.info("no span here")
    [line] = sink.lines
    assert "traceId" not in line
    assert "spanId" not in line
    assert "correlationId" not in line
    assert line["event"] == "no span here"
    assert line["level"] == "info"
    assert line["logger"] == sink.logger.name
    assert line["timestamp"].endswith("Z")


def test_r58_a_record_inside_a_span_renders_that_spans_ids(sink: Sink) -> None:
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("unit") as span:
        sink.logger.info("inside")
        context = span.get_span_context()
    [line] = sink.lines
    assert line["traceId"] == format(context.trace_id, "032x")
    assert line["spanId"] == format(context.span_id, "016x")


def test_r58_extra_fields_are_rendered(sink: Sink) -> None:
    sink.logger.warning("with extras", extra={"offset": 41, "topic": "t.facts"})
    [line] = sink.lines
    assert line["offset"] == 41
    assert line["topic"] == "t.facts"


def test_r58_non_ascii_is_written_raw_not_escaped(sink: Sink) -> None:
    sink.logger.info("pedido de ñandú 日本")
    assert "pedido de ñandú 日本" in sink.text
    assert "\\u" not in sink.text


def test_r58_a_binding_does_not_outlive_its_unit_in_one_task(sink: Sink) -> None:
    with structlog.contextvars.bound_contextvars(correlationId=FIRST):
        sink.logger.info("first unit")
    sink.logger.info("between units")
    with structlog.contextvars.bound_contextvars(correlationId=SECOND):
        sink.logger.info("second unit")
    first, between, second = sink.lines
    assert first["correlationId"] == FIRST
    assert "correlationId" not in between
    assert second["correlationId"] == SECOND


def test_l7_a_synchronous_handler_carries_the_active_spans_trace_id(sink: Sink) -> None:
    """Ledger L7, the kept half: formatting happens in the emitting context. The other half (the
    same formatter behind a QueueHandler loses the id) is a recorded probe in the implementation
    record, not a kept test."""
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("unit") as span:
        sink.logger.info("sync")
        expected = format(span.get_span_context().trace_id, "032x")
    assert sink.lines[0]["traceId"] == expected


def test_r58_uvicorns_ansi_coloured_copy_of_a_message_is_not_rendered(sink: Sink) -> None:
    sink.logger.info("Started server process [7]", extra={"color_message": "\x1b[36m%d\x1b[0m"})
    [line] = sink.lines
    assert line["event"] == "Started server process [7]"
    assert "color_message" not in line
    assert "\\u001b" not in sink.text
