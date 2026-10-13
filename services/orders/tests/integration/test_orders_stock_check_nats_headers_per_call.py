"""R56: `NatsStockAvailability` builds its NATS headers PER CALL (feature 27 `design.md` 4.4; S3.7,
ledger L23; #8 D9).

`orders.create` requests run concurrently and share this one adapter. Two concurrent stock checks
(distinguished by their company code) under two DISTINCT caller spans reach `request` together: the
first is held there until the second has built ITS headers (`HoldingConnection`, created by the
test, no delay of any other kind). A real NATS subscriber records the headers each request actually
arrived with, and each must carry its own call's trace id. A headers dict shared between calls
(hoisted onto the adapter) fails on that overlap alone.
"""

import asyncio
import contextlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from otc_orders.application.ports.stock_availability import StockAvailabilityLine
from otc_orders.infrastructure.messaging.nats_stock_availability import NatsStockAvailability
from otc_orders.infrastructure.messaging.subjects import STOCK_CHECK_SUBJECT
from otc_orders.infrastructure.observability.telemetry import build_telemetry
from otc_shared_kernel import Quantity

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

ERROR_REPLY = b'{"code":"INTERNAL_ERROR","message":"stand-in"}'
COMPANIES = ("CMP-ALPHA", "CMP-OMEGA")


async def test_r56_two_concurrent_stock_checks_each_carry_their_own_calls_trace_id(
    nats_server: Any, nats_client: Any
) -> None:
    receiver = await support.Receiver.start(nats_server.url, [STOCK_CHECK_SUBJECT], ERROR_REPLY)
    telemetry = build_telemetry("orders", "")
    adapter = NatsStockAvailability(
        cast("Any", support.HoldingConnection(nats_client)),
        timeout_ms=5000,
        tracer=telemetry.tracer,
    )
    callers = {company: support.caller_tracer() for company in COMPANIES}
    expected: dict[str, int] = {}

    async def check(company: str) -> None:
        with callers[company].start_as_current_span(f"caller {company}") as origin:
            expected[company] = origin.get_span_context().trace_id
            with contextlib.suppress(Exception):  # the stand-in answers an RpcError
                await adapter.check(company, [StockAvailabilityLine("SKU-A", Quantity(1))])

    try:
        await asyncio.gather(*(check(company) for company in COMPANIES))
    finally:
        await receiver.close()
        telemetry.shutdown()

    assert expected[COMPANIES[0]] != expected[COMPANIES[1]], (
        "the calls must run under distinct traces"
    )
    seen = {
        json.loads(body)["companyCode"]: support.trace_id_of_header(headers)
        for _, body, headers in receiver.received
    }
    assert seen == expected, "a call's request arrived carrying another call's trace"
