"""R56: `NatsRpcClient` builds its NATS headers PER CALL (feature 27 `design.md` 4.4; S3.7, ledger
L23; #8 D9).

Two concurrent calls under two DISTINCT caller spans reach the client's `request` together: the
first is held there until the second has arrived (`HoldingConnection`, created by the test, no
delay of any other kind), i.e. until the second has already built ITS headers. A real NATS
subscriber then records the headers each request actually arrived with, and each must carry its own
call's trace id. A headers dict shared between calls (hoisted onto the client) fails on that
overlap alone.
"""

import asyncio
import contextlib
import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import nats
from nats.aio.client import Client

from otc_contracts.generated.asyncapi import CreditHoldReplyPayload, StockListRequestPayload
from otc_gateway.infrastructure.nats_rpc_client import NatsRpcClient
from otc_gateway.infrastructure.observability.telemetry import build_telemetry

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

SUBJECT_A = "test.headers.a"
SUBJECT_B = "test.headers.b"
ERROR_REPLY = b'{"code":"INTERNAL_ERROR","message":"stand-in"}'


async def test_r56_two_concurrent_gateway_rpc_calls_each_carry_their_own_calls_trace_id(
    nats_server: Any,
) -> None:
    caller_connection = await nats.connect(nats_server.url)
    receiver = await support.Receiver.start(nats_server.url, [SUBJECT_A, SUBJECT_B], ERROR_REPLY)
    telemetry = build_telemetry("gateway", "")
    client = NatsRpcClient(
        cast("Client", support.HoldingConnection(caller_connection)),
        timeout_ms=5000,
        tracer=telemetry.tracer,
    )
    callers = {SUBJECT_A: support.caller_tracer(), SUBJECT_B: support.caller_tracer()}
    expected: dict[str, int] = {}

    async def call(subject: str) -> None:
        with callers[subject].start_as_current_span(f"caller {subject}") as origin:
            expected[subject] = origin.get_span_context().trace_id
            # the stand-in answers an RpcError: only the headers it received matter
            with contextlib.suppress(Exception):
                await client.call(
                    subject,
                    StockListRequestPayload(),
                    CreditHoldReplyPayload,
                    correlation_id=uuid.uuid4(),
                    request_id=uuid.uuid4(),
                )

    try:
        await asyncio.gather(call(SUBJECT_A), call(SUBJECT_B))
    finally:
        await receiver.close()
        await caller_connection.close()
        telemetry.shutdown()

    assert expected[SUBJECT_A] != expected[SUBJECT_B], (
        "the two calls must run under distinct traces"
    )
    seen = {
        subject: support.trace_id_of_header(headers) for subject, _, headers in receiver.received
    }
    assert sorted(seen) == [SUBJECT_A, SUBJECT_B], (
        f"both requests must reach the subscriber: {seen}"
    )
    assert all(seen.values()), (
        "R56 hop Gateway -> NATS: a request arrived with NO traceparent (trace id 0): "
        f"NatsRpcClient did not inject the call's span context {seen}"
    )
    assert seen == expected, "a call's request arrived carrying another call's trace"
