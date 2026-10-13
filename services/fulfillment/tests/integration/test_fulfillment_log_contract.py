"""R58 for Fulfillment: every line the REAL server writes is JSON; one unit of work carries its id.

A real `python -m uvicorn otc_fulfillment.main:app --port 0` child over the suite's Docker-held
PostgreSQL and NATS (the relay is off, as in `host_environment`). The unit of work is one RPC
request on `fulfillment.stock.reserve` carrying an `x-correlation-id` and a `traceparent` and NO
payload, which the responder refuses, so the line `fulfillment.stock.reserve refused: ...` is
written by the responder itself with NO explicit correlation argument: only the binding of `_serve`
can put `correlationId` on it. The child is stopped with SIGTERM and EVERY stderr line is judged
(`tests/observability/log_contract_support.py`).

Both halves of the claim are asserted (S3): the lines carrying the unit's `correlationId` are
exactly the lines carrying the `traceId` of the inbound `traceparent` the test sent, and the unit's
lines carry that trace id (the process continued the trace; a fresh root would carry another).
Loop scope: function.
"""

import importlib.util
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from nats.aio.client import Client as NatsClient

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/log_contract_support.py"
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_ID = TRACEPARENT.split("-")[1]


def load_support() -> Any:
    spec = importlib.util.spec_from_file_location("log_contract_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_r58_every_line_the_real_server_writes_is_json_and_every_line_of_one_unit_of_work_carries_its_correlation_id_and_trace_id(  # noqa: E501
    host_environment: Callable[..., None], nats_client: NatsClient, tmp_path: Path
) -> None:
    support = load_support()
    host_environment()
    correlation_id = str(uuid.uuid4())
    process = support.spawn(
        support.python_module("uvicorn", "otc_fulfillment.main:app", "--port", "0"),
        cwd=tmp_path,
        tmp_path=tmp_path,
        name="fulfillment",
    )
    try:
        await support.wait_for_event(
            process, "Fulfillment's application startup complete", support.booted
        )
        reply = await nats_client.request(
            "fulfillment.stock.reserve",
            b"",
            headers={"x-correlation-id": correlation_id, "traceparent": TRACEPARENT},
            timeout=10,
        )
        assert json.loads(reply.data)["code"], reply.data
        await support.wait_for_event(
            process,
            "the line the refused request writes",
            lambda line: "fulfillment.stock.reserve refused" in line.get("event", ""),
        )
        exit_code = await support.stop(process)
    finally:
        support.kill(process)
    assert exit_code in {0, -15}, process.stderr_text()

    lines = support.check_contract(
        process,
        correlation_id=correlation_id,
        trace_id=TRACE_ID,
        provoked={
            "fulfillment.stock.reserve refused": lambda line: (
                line["logger"] == "otc_fulfillment.presentation.stock_responder"
                and "fulfillment.stock.reserve refused" in line["event"]
            )
        },
    )
    assert any(line.get("traceId") == TRACE_ID for line in lines), (
        f"no line carries the inbound traceId {TRACE_ID}: the responder did not continue the trace"
    )
