"""R56: `NatsSagaCommandsAdapter` builds its NATS headers PER CALL (feature 27 `design.md` 4.4;
S3.7, orchestrator L19, ledger L23; #8 D9).

The adapter is shared by concurrent per-command tasks. Two concurrent commands (`stock.reserve` and
`credit.hold`) under two DISTINCT caller spans reach `request` together: the first is held there
until the second has built ITS headers (`HoldingConnection`, created by the test, no delay of any
other kind). A real NATS subscriber then records the headers each request actually arrived with,
and each must carry its own command's trace id. A headers dict shared between calls (hoisted onto
the adapter) fails on that overlap alone.
"""

import asyncio
import contextlib
import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from otc_orders.application.ports.saga_commands import SagaCommandMeta
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.messaging.nats_saga_commands import NatsSagaCommandsAdapter
from otc_orders.infrastructure.messaging.saga_subjects import SAGA_SUBJECTS
from otc_orders.infrastructure.observability.telemetry import build_telemetry
from otc_shared_kernel import UniqueId

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


async def test_r56_two_concurrent_saga_commands_each_carry_their_own_commands_trace_id(
    nats_server: Any, nats_client: Any
) -> None:
    subject_a = SAGA_SUBJECTS[SagaCommandKind.STOCK_RESERVE]
    subject_b = SAGA_SUBJECTS[SagaCommandKind.CREDIT_HOLD]
    assert subject_a != subject_b
    receiver = await support.Receiver.start(nats_server.url, [subject_a, subject_b], ERROR_REPLY)
    telemetry = build_telemetry("orders", "")
    adapter = NatsSagaCommandsAdapter(
        cast("Any", support.HoldingConnection(nats_client)),
        timeout_ms=5000,
        tracer=telemetry.tracer,
    )
    callers = {subject_a: support.caller_tracer(), subject_b: support.caller_tracer()}
    expected: dict[str, int] = {}

    async def reserve() -> None:
        meta = SagaCommandMeta(correlation_id=UniqueId.new(), request_id=uuid.uuid4())
        with callers[subject_a].start_as_current_span("caller a") as origin:
            expected[subject_a] = origin.get_span_context().trace_id
            with contextlib.suppress(Exception):  # the stand-in answers an RpcError
                await adapter.reserve_stock(b"{}", meta)

    async def hold() -> None:
        meta = SagaCommandMeta(correlation_id=UniqueId.new(), request_id=uuid.uuid4())
        with callers[subject_b].start_as_current_span("caller b") as origin:
            expected[subject_b] = origin.get_span_context().trace_id
            with contextlib.suppress(Exception):
                await adapter.hold_credit(b"{}", meta)

    try:
        await asyncio.gather(reserve(), hold())
    finally:
        await receiver.close()
        telemetry.shutdown()

    assert expected[subject_a] != expected[subject_b], "the commands must run under distinct traces"
    seen = {s: support.trace_id_of_header(h) for s, _, h in receiver.received}
    assert seen == expected, "a command's request arrived carrying another command's trace"
