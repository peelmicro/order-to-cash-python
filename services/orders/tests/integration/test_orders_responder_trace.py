"""R56 / OR4: the Orders responder continues the caller's trace (feature 27 `design.md` 4.4; S3.6).

Through the PRODUCTION responder (`OrdersCreateResponder`, built by the real `start_runtime`) over
real NATS, PostgreSQL and Kafka. The caller's span comes from a provider of the test's own, so a
`SERVER` span the runtime exports can only share its trace id by having EXTRACTED the header. The
spans read back are the runtime's own provider's. A request without a header must start a root
span of its own, and the outbox row it writes must record THAT trace, not the caller's.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import asyncpg

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

REQUEST: dict[str, Any] = {
    "retailerCode": "RET-01",
    "companyCode": "CMP-01",
    "currency": "EUR",
    "lines": [{"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999, "lineDiscount": 250}],
}


async def stored_trace_parent(dsn: str, order_id: str) -> str:
    conn = await asyncpg.connect(dsn)
    try:
        value: str | None = await conn.fetchval(
            "SELECT trace_parent FROM outbox WHERE aggregate_id = $1::uuid", order_id
        )
    finally:
        await conn.close()
    assert value is not None, "the order's outbox row recorded no trace"
    return value


async def place(host: Any, headers: dict[str, str] | None) -> dict[str, Any]:
    reply = await host.client.request(
        "orders.create", json.dumps(REQUEST).encode(), timeout=10, headers=headers
    )
    body: dict[str, Any] = json.loads(reply.data)
    assert body["status"] == "placed", body
    return body


async def test_r56_a_request_with_a_traceparent_is_served_inside_the_callers_trace_and_its_outbox_row_records_the_continued_span(  # noqa: E501
    traced_orders_factory: Any, stand_in_stock_check: Any, stock_reply: Any, migrated_db: Any
) -> None:
    await stand_in_stock_check(lambda request: stock_reply([("SKU-A", 3, 50)]))
    with support.caller_tracer().start_as_current_span("caller") as origin:
        caller = origin.get_span_context()
        headers = support.traceparent_header_of_current_span()

    async with traced_orders_factory(OUTBOX_RELAY_ENABLED="false") as host:
        body = await place(host, headers)

    infos = support.span_infos(host.exporter)
    (server,) = support.by_name(infos, "orders.create serve")
    (transaction,) = support.by_name(infos, "writemodel.transaction")
    assert (server.trace_id, server.parent_id) == (caller.trace_id, caller.span_id)
    stored = (await stored_trace_parent(migrated_db.dsn, body["orderId"])).split("-")
    assert stored[1:3] == [
        support.trace_hex(caller.trace_id),
        support.span_hex(transaction.span_id),
    ], "the row records the transaction span, a descendant of the caller's span"


async def test_r56_a_request_without_a_traceparent_starts_its_own_root_and_its_outbox_row_records_that_root(  # noqa: E501
    traced_orders_factory: Any, stand_in_stock_check: Any, stock_reply: Any, migrated_db: Any
) -> None:
    await stand_in_stock_check(lambda request: stock_reply([("SKU-A", 3, 50)]))
    with support.caller_tracer().start_as_current_span("caller") as origin:
        caller = origin.get_span_context()

    async with traced_orders_factory(OUTBOX_RELAY_ENABLED="false") as host:
        body = await place(host, None)

    infos = support.span_infos(host.exporter)
    (server,) = support.by_name(infos, "orders.create serve")
    (transaction,) = support.by_name(infos, "writemodel.transaction")
    assert server.parent_id is None, "no header: the server span is a root"
    assert server.trace_id != caller.trace_id
    stored = (await stored_trace_parent(migrated_db.dsn, body["orderId"])).split("-")
    assert stored[1:3] == [
        support.trace_hex(server.trace_id),
        support.span_hex(transaction.span_id),
    ]
