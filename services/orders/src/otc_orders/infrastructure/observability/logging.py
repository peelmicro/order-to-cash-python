"""One JSON line per log record, whoever wrote it (`R58`, `OR7`; the spec's `design.md` 2.1 - 2.2).

structlog is the RENDERER and stdlib `logging` stays the call API: one synchronous
`logging.StreamHandler(sys.stderr)` on the root logger whose formatter is
`structlog.stdlib.ProcessorFormatter`. Every record, ours and every library's, passes the same
`foreign_pre_chain`, so a line carries `level`, `logger`, `event`, `timestamp` (the wire's one
instant format), the `extra` fields the call site passed, `correlationId` when a unit of work bound
one (`structlog.contextvars`, see `tests/architecture/test_correlation_binding_sites.py`) and
`traceId` / `spanId` when a valid span is active, and NEITHER key when none is (never an empty
value).

The handler is synchronous on purpose: `add_trace_context` reads the active span at FORMAT time, in
the emitting task's context. Behind a `QueueHandler` the formatting would happen on another thread,
where the current span is the invalid one, and every line would silently lose its trace (ledger L7;
probed both ways in `tests/unit/test_log_rendering.py`).

`install_json_logging` is called at MODULE level in `main.py`, before `create_app()`: uvicorn
installs its own `LOGGING_CONFIG` in `Config.__init__`, imports the app afterwards and only then
logs `Started server process`, so configuring in the lifespan would leave that line in uvicorn's
plain-text format. It is idempotent, never removes another root handler (pytest's `caplog` handler
survives) and re-routes the three uvicorn loggers to the root handler.

This file is canonical in Orders and copied to the other five services
(`tests/architecture/test_observability_copy_parity.py`).
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Final

import structlog
from opentelemetry import trace
from structlog.typing import EventDict, WrappedLogger

from otc_contracts.wire import format_instant

FOREIGN_HANDLER_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access")
"""Loggers that bring their own handler and `propagate = False`; their lines must reach the root."""

_HANDLER_TAG: Final = "_otc_json_logging_service"


def add_trace_context(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """`traceId` / `spanId` of the span active in the emitting context; neither key when invalid."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["traceId"] = format(context.trace_id, "032x")
        event_dict["spanId"] = format(context.span_id, "016x")
    return event_dict


def drop_color_message(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """uvicorn hands every line a second, ANSI-coloured copy of its message as an `extra`."""
    event_dict.pop("color_message", None)
    return event_dict


def add_timestamp(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """`timestamp` through the wire's instant formatter (`YYYY-MM-DDTHH:MM:SS.mmmZ`)."""
    record = event_dict.get("_record")
    instant = (
        datetime.fromtimestamp(record.created, UTC)
        if isinstance(record, logging.LogRecord)
        else datetime.now(UTC)
    )
    event_dict["timestamp"] = format_instant(instant)
    return event_dict


def serialize(event: Any, **kwargs: Any) -> str:
    """Compact JSON, non-ASCII written raw (CLAUDE.md "JSON wire shape", applied to log lines)."""
    return json.dumps(event, separators=(",", ":"), ensure_ascii=False, **kwargs)


def build_formatter() -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.ExtraAdder(),
            drop_color_message,
            add_trace_context,
            add_timestamp,
            structlog.processors.format_exc_info,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(serializer=serialize),
        ],
    )


def install_json_logging(service: str) -> None:
    """Install the one JSON handler on the root logger; a second call adds nothing."""
    root = logging.getLogger()
    if not any(hasattr(handler, _HANDLER_TAG) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(build_formatter())
        setattr(handler, _HANDLER_TAG, service)
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in FOREIGN_HANDLER_LOGGERS:
        foreign = logging.getLogger(name)
        foreign.handlers.clear()
        foreign.propagate = True
