"""FS4 (H8): each `fulfillment.stock.*` request is a BARE JSON payload and each reply a BARE JSON
success payload or `RpcError`: no `{"response": ...}` packet envelope, no `isDisposed`, no `id`.
The bytes are compact (no whitespace after `:` or `,`) and parse as the generated model."""

import json
import uuid
from typing import Any

import pytest

from otc_contracts import from_wire_json
from otc_contracts.generated import asyncapi
from otc_contracts.wire import WireModel

COMPANY = "ACME-CO"
HEADERS = {"x-correlation-id": str(uuid.UUID(int=0xC0)), "x-request-id": str(uuid.UUID(int=0xCA))}
FORBIDDEN = {"response", "isDisposed", "id"}

CASES: dict[str, tuple[dict[str, Any], dict[str, str] | None, type[WireModel], set[str]]] = {
    "fulfillment.stock.check": (
        {"companyCode": COMPANY, "lines": [{"productCode": "PRD-A1", "quantity": 2}]},
        None,
        asyncapi.StockCheckReplyPayload,
        {"available", "lines"},
    ),
    "fulfillment.stock.reserve": (
        {
            "orderReference": "ORD-000042",
            "retailerCode": "RET-9",
            "companyCode": COMPANY,
            "lines": [{"productCode": "PRD-A1", "units": 2}],
        },
        HEADERS,
        asyncapi.StockReserveReplyPayload,
        {"outcome", "orderReference", "reservations"},  # `shortages` is absent: not "present when"
    ),
    "fulfillment.stock.release": (
        {"orderReference": "ORD-000042", "reason": "order_cancelled"},
        HEADERS,
        asyncapi.StockReleaseReplyPayload,
        {"outcome", "orderReference", "released"},
    ),
    "fulfillment.stock.list": ({}, None, asyncapi.StockListReplyPayload, {"items", "page"}),
    "fulfillment.stock.replenish": (
        {"companyCode": COMPANY, "lines": [{"productCode": "PRD-A1", "units": 2}]},
        None,
        asyncapi.StockReplenishReplyPayload,
        {"items"},
    ),
}


def assert_compact(raw: bytes) -> None:
    text = raw.decode("utf-8")
    assert text == json.dumps(json.loads(text), separators=(",", ":"), ensure_ascii=False), (
        "the reply is written by the one serializer: compact, nothing re-spaced"
    )


@pytest.mark.parametrize("subject", sorted(CASES))
async def test_fs4_answers_a_bare_json_request_with_a_bare_json_reply_on_all_five_subjects(
    fulfillment_host: Any, db: Any, nats_client: Any, subject: str
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])
    body, headers, model, expected_keys = CASES[subject]
    if subject == "fulfillment.stock.release":  # a release needs something to release
        await nats_client.request(
            "fulfillment.stock.reserve",
            json.dumps(CASES["fulfillment.stock.reserve"][0]).encode(),
            timeout=15,
            headers=HEADERS,
        )

    message = await nats_client.request(
        subject, json.dumps(body).encode(), timeout=15, headers=headers
    )

    reply = json.loads(message.data)
    assert set(reply) == expected_keys, "exactly the reply schema's properties that are present"
    assert FORBIDDEN.isdisjoint(reply), "no packet envelope around the reply"
    assert_compact(message.data)
    from_wire_json(model, message.data)  # parses as the generated model, strictly


async def test_fs4_answers_a_bare_json_rpc_error_on_a_validation_failure(
    fulfillment_host: Any, nats_client: Any
) -> None:
    message = await nats_client.request(
        "fulfillment.stock.check", b'{"companyCode":"ACME-CO","lines":[]}', timeout=15
    )

    reply = json.loads(message.data)
    assert set(reply) <= {"code", "message", "details", "correlationId", "occurredAt"}
    assert {"code", "message"} <= set(reply)
    assert reply["code"] == "VALIDATION_FAILED"
    assert FORBIDDEN.isdisjoint(reply)
    assert_compact(message.data)
    error = from_wire_json(asyncapi.RpcError, message.data)
    assert error.code is asyncapi.Code.validation_failed
    assert reply["occurredAt"].endswith("Z")
    assert len(reply["occurredAt"]) == len("2026-10-08T09:30:05.123Z")


async def test_a_request_that_is_not_json_at_all_is_still_answered_with_a_bare_rpc_error(
    fulfillment_host: Any, nats_client: Any
) -> None:
    for subject in (
        "fulfillment.stock.check",
        "fulfillment.stock.reserve",
        "fulfillment.stock.release",
        "fulfillment.stock.list",
        "fulfillment.stock.replenish",
    ):
        message = await nats_client.request(subject, b"{this is not json", timeout=15)
        assert json.loads(message.data)["code"] == "VALIDATION_FAILED", subject
