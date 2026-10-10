"""The bare-JSON wire of the three subjects against the real responder (task H7; BC2).

No framework packet envelope: a request is a bare JSON object, the reply a bare JSON object or a
bare `RpcError`. The reply is decoded with `json.loads` first (NO `response`, `isDisposed` or `id`
key can be there), then through the generated model.

Loop scope: function. The host and the caller are created and closed in the test's loop.
"""

import json
import uuid
from typing import Any

from nats.aio.client import Client as NatsClient

from otc_contracts import from_wire_json
from otc_contracts.generated import asyncapi

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER = "ORD-000101"
FRAMEWORK_KEYS = {"response", "isDisposed", "id", "err", "data", "pattern"}


def headers() -> dict[str, str]:
    return {"x-correlation-id": str(uuid.uuid4()), "x-request-id": str(uuid.uuid4())}


async def raw(client: NatsClient, subject: str, body: bytes, hdrs: dict[str, str] | None) -> bytes:
    reply = await client.request(subject, body, timeout=15, headers=hdrs)
    return bytes(reply.data)


async def test_bc2_answers_a_bare_json_request_with_a_bare_json_reply_on_all_three_subjects(
    billing_host: Any, db: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    client: NatsClient = billing_host.client
    hold_body = json.dumps(
        {
            "orderReference": ORDER,
            "retailerCode": RETAILER,
            "companyCode": COMPANY,
            "amount": {"amount": 4210, "currency": "EUR"},
        }
    ).encode()
    release_body = json.dumps(
        {"orderReference": ORDER, "retailerCode": RETAILER, "companyCode": COMPANY}
    ).encode()

    hold = json.loads(await raw(client, "billing.credit.hold", hold_body, headers()))
    assert "outcome" in hold, f"BC2: not a hold reply: {hold}"
    assert FRAMEWORK_KEYS.isdisjoint(hold), f"BC2: a framework key wraps the reply: {hold}"
    assert (
        from_wire_json(asyncapi.CreditHoldReplyPayload, json.dumps(hold).encode()).held_amount
        == 4210
    )

    released = json.loads(await raw(client, "billing.credit.release", release_body, headers()))
    assert "released" in released, f"BC2: not a release reply: {released}"
    assert FRAMEWORK_KEYS.isdisjoint(released), f"BC2: a framework key wraps the reply: {released}"
    assert (
        from_wire_json(asyncapi.CreditReleaseReplyPayload, json.dumps(released).encode()).released
        is True
    )

    listed = json.loads(await raw(client, "billing.credit.list", b"{}", None))
    assert "page" in listed, f"BC2: not a list reply: {listed}"
    assert FRAMEWORK_KEYS.isdisjoint(listed), f"BC2: a framework key wraps the reply: {listed}"
    decoded = from_wire_json(asyncapi.CreditListReplyPayload, json.dumps(listed).encode())
    assert decoded.page.total == 1


async def test_bc2_answers_a_bare_json_rpc_error_on_a_validation_failure(billing_host: Any) -> None:
    client: NatsClient = billing_host.client
    for subject, body, hdrs in (
        ("billing.credit.hold", b'{"orderReference": "nope"}', headers()),
        ("billing.credit.release", b"not json", headers()),
        ("billing.credit.list", b'{"pageSize": 0}', None),
    ):
        error = json.loads(await raw(client, subject, body, hdrs))
        assert "code" in error, f"BC2: {subject} did not answer an RpcError: {error}"
        assert FRAMEWORK_KEYS.isdisjoint(error), f"BC2: a framework key wraps the error: {error}"
        decoded = from_wire_json(asyncapi.RpcError, json.dumps(error).encode())
        assert decoded.code.value == "VALIDATION_FAILED", subject
        assert decoded.message
