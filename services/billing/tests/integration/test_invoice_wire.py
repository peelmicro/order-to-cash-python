"""Both invoice subjects answer BARE JSON, and a refusal is a bare `RpcError` (task G3; BI16).

The replies are decoded with plain `json.loads` FIRST: no `response`, `isDisposed` or `id` key (the
framework packet envelope #7's NestJS transport would add); only then are they parsed through the
generated models.

Loop scope: function.
"""

import json
import uuid
from typing import Any

from otc_contracts import from_wire_json
from otc_contracts.generated import asyncapi

PACKET_KEYS = {"response", "isDisposed", "id", "err"}
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"


async def raw_request(
    client: Any, subject: str, body: bytes, headers: dict[str, str] | None = None
) -> bytes:
    message = await client.request(subject, body, timeout=15, headers=headers)
    return bytes(message.data)


def headers() -> dict[str, str]:
    return {"x-correlation-id": str(uuid.uuid4()), "x-request-id": str(uuid.uuid4())}


async def test_bi16_both_invoice_subjects_answer_bare_json_and_a_refusal_is_a_bare_rpc_error(
    billing_host: Any, db: Any, rpc: Any, decode: Any, nats_client: Any, issue_body: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=250_000, code="CR-000321")
    built = issue_body(
        [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)],
        350,
        order_reference="ORD-000101",
        retailer_code=RETAILER,
        company_code=COMPANY,
    )
    held = await rpc(
        "billing.credit.hold",
        {
            "orderReference": "ORD-000101",
            "retailerCode": RETAILER,
            "companyCode": COMPANY,
            "amount": {"amount": built.total, "currency": "EUR"},
        },
        headers=headers(),
    )
    assert decode.hold(held).outcome.value == "approved"

    # --- billing.invoice.issue: a success
    issue_bytes = await raw_request(
        billing_host.client, "billing.invoice.issue", json.dumps(built.body).encode(), headers()
    )
    issue_reply = json.loads(issue_bytes)
    assert isinstance(issue_reply, dict)
    assert "created" in issue_reply, f"BI16: not an issue reply: {issue_reply}"
    wrapped = sorted(PACKET_KEYS & set(issue_reply))
    assert not wrapped, f"BI16: the issue reply carries a framework envelope key: {wrapped}"
    parsed = from_wire_json(asyncapi.InvoiceIssueReplyPayload, issue_bytes)
    assert parsed.created is True

    # --- billing.invoice.list: a success
    list_bytes = await raw_request(billing_host.client, "billing.invoice.list", b"{}")
    list_reply = json.loads(list_bytes)
    assert "page" in list_reply, f"BI16: not a list reply: {list_reply}"
    assert PACKET_KEYS.isdisjoint(list_reply)
    assert from_wire_json(asyncapi.InvoiceListReplyPayload, list_bytes).page.total == 1

    # --- a refusal on each subject is a BARE RpcError
    refused_issue = await raw_request(
        billing_host.client, "billing.invoice.issue", b'{"lines": []}', headers()
    )
    refused_list = await raw_request(billing_host.client, "billing.invoice.list", b'{"page": 0}')
    for label, refusal in (("issue", refused_issue), ("list", refused_list)):
        decoded = json.loads(refusal)
        assert "code" in decoded, f"BI16: the {label} refusal is not an RpcError: {decoded}"
        assert PACKET_KEYS.isdisjoint(decoded), f"BI16: the {label} refusal is wrapped: {decoded}"
        error = from_wire_json(asyncapi.RpcError, refusal)
        assert error.code.value == "VALIDATION_FAILED"
