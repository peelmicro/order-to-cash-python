"""R56 / OR4: the Fulfillment responder continues the caller's trace (feature 27 `design.md` 4.4;
S3.6).

Through the PRODUCTION responder (`StockResponder`, built by the real `start_runtime`) over real
NATS and PostgreSQL, using `fulfillment.stock.reserve`, a subject that WRITES (a `stock.reserved.v1`
outbox row). The caller's span is made by a provider of the test's own, so a `SERVER` span the
runtime exports can only share its trace id by having EXTRACTED the header; the spans read back are
the runtime's own provider's. Without a header the server span must be a root of its own and the
outbox row must record that root, not the caller's trace.
"""

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

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

COMPANY = "ACME-CO"
RETAILER = "RET-9"
ORDER = "ORD-000042"
BODY = {
    "orderReference": ORDER,
    "retailerCode": RETAILER,
    "companyCode": COMPANY,
    "lines": [{"productCode": "PRD-A1", "units": 3}],
}


def ids() -> dict[str, str]:
    return {"x-correlation-id": str(uuid.uuid4()), "x-request-id": str(uuid.uuid4())}


async def stored_trace_parent(db: Any) -> str:
    rows = await db.fetch("SELECT trace_parent FROM outbox")
    assert len(rows) == 1, f"expected the one stock.reserved.v1 row, found {len(rows)}"
    value: str | None = rows[0]["trace_parent"]
    assert value is not None, "the outbox row recorded no trace"
    return value


async def test_r56_a_request_with_a_traceparent_is_served_inside_the_callers_trace_and_its_outbox_row_records_the_continued_span(  # noqa: E501
    traced_fulfillment_factory: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])
    with support.caller_tracer().start_as_current_span("caller") as origin:
        caller = origin.get_span_context()
        headers = ids() | support.traceparent_header_of_current_span()

    async with traced_fulfillment_factory() as host:
        reply = await rpc("fulfillment.stock.reserve", BODY, headers=headers)
    assert reply["outcome"] == "accepted", reply

    infos = support.span_infos(host.exporter)
    (server,) = support.by_name(infos, "fulfillment.stock.reserve serve")
    (transaction,) = support.by_name(infos, "writemodel.transaction")
    assert (server.trace_id, server.parent_id) == (caller.trace_id, caller.span_id)
    assert (transaction.trace_id, transaction.parent_id) == (server.trace_id, server.span_id)
    stored = (await stored_trace_parent(db)).split("-")
    assert stored[1:3] == [
        support.trace_hex(caller.trace_id),
        support.span_hex(transaction.span_id),
    ]


async def test_r56_a_request_without_a_traceparent_starts_its_own_root_and_its_outbox_row_records_that_root(  # noqa: E501
    traced_fulfillment_factory: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])
    with support.caller_tracer().start_as_current_span("caller") as origin:
        caller = origin.get_span_context()

    async with traced_fulfillment_factory() as host:
        reply = await rpc("fulfillment.stock.reserve", BODY, headers=ids())
    assert reply["outcome"] == "accepted", reply

    infos = support.span_infos(host.exporter)
    (server,) = support.by_name(infos, "fulfillment.stock.reserve serve")
    (transaction,) = support.by_name(infos, "writemodel.transaction")
    assert server.parent_id is None, "no header: the server span is a root"
    assert server.trace_id != caller.trace_id
    stored = (await stored_trace_parent(db)).split("-")
    assert stored[1:3] == [
        support.trace_hex(server.trace_id),
        support.span_hex(transaction.span_id),
    ]
