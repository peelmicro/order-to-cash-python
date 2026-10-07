"""`orders.create` request validation, over the wire, with NO Fulfillment stand-in subscribed.

The absence of a stand-in is the design (#8 round 3, D5): a request that were NOT validated would
get past the checks and come back as a DIFFERENT code (`NOT_FOUND` for a blank code, `UNAVAILABLE`
for the stock check that nobody answers, `INTERNAL_ERROR` for a missing field), never accidentally
`VALIDATION_FAILED`. So each case below proves the validator ran AND, by arming the call site,
that deleting the call fails it.

Required by `asyncapi.yaml` `OrdersCreateRequestPayload`: `retailerCode`, `companyCode`, `currency`
(`^[A-Z]{3}$`), `lines` (min 1); per line `productCode` and `quantity` (>= 1).
"""

import json
from typing import Any

import asyncpg
import pytest
from nats.aio.client import Client as NatsClient

LINE = {"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999, "lineDiscount": 250}
GOOD: dict[str, Any] = {
    "retailerCode": "RET-01",
    "companyCode": "CMP-01",
    "currency": "EUR",
    "lines": [LINE],
}


def without(*names: str) -> dict[str, Any]:
    return {k: v for k, v in GOOD.items() if k not in names}


def line(**changes: Any) -> dict[str, Any]:
    return {k: v for k, v in (LINE | changes).items() if v is not None}


CASES: dict[str, Any] = {
    "retailerCode missing": without("retailerCode"),
    "retailerCode empty": GOOD | {"retailerCode": ""},
    "retailerCode blank": GOOD | {"retailerCode": "   "},
    "retailerCode over 20 characters": GOOD | {"retailerCode": "R" * 21},
    "retailerCode not a string": GOOD | {"retailerCode": 7},
    "companyCode missing": without("companyCode"),
    "companyCode empty": GOOD | {"companyCode": ""},
    "companyCode over 20 characters": GOOD | {"companyCode": "C" * 21},
    "companyCode blank": GOOD | {"companyCode": "\t"},
    "currency missing": without("currency"),
    "currency empty": GOOD | {"currency": ""},
    "currency lower case": GOOD | {"currency": "eur"},
    "currency four letters": GOOD | {"currency": "EURO"},
    "lines missing": without("lines"),
    "lines empty": GOOD | {"lines": []},
    "lines not a list": GOOD | {"lines": "SKU-A"},
    "line productCode missing": GOOD | {"lines": [line(productCode=None)]},
    "line productCode empty": GOOD | {"lines": [line(productCode="")]},
    "line productCode blank": GOOD | {"lines": [line(productCode=" ")]},
    "line productCode over 30 characters": GOOD | {"lines": [line(productCode="P" * 31)]},
    "second line productCode missing": GOOD | {"lines": [LINE, line(productCode=None)]},
    "line quantity missing": GOOD | {"lines": [line(quantity=None)]},
    "line quantity zero": GOOD | {"lines": [line(quantity=0)]},
    "line quantity negative": GOOD | {"lines": [line(quantity=-2)]},
    "line quantity a string": GOOD | {"lines": [line(quantity="3")]},
    "line quantity fractional": GOOD | {"lines": [line(quantity=2.5)]},
    "line quantity a boolean": GOOD | {"lines": [line(quantity=True)]},
    "unitPrice a float": GOOD | {"lines": [line(unitPrice=19.99)]},
    "body is a JSON array": [GOOD],
    "body is a JSON null": None,
}
RAW_BODIES = {
    "body is not JSON": b"{retailerCode: RET-01",
    "body is empty": b"",
    "body is not UTF-8": b"\xff\xfe\x00",
}


async def orders_count(dsn: str) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        return int(await conn.fetchval("SELECT count(*) FROM orders"))
    finally:
        await conn.close()


async def refused(client: NatsClient, body: bytes) -> dict[str, Any]:
    reply = await client.request("orders.create", body, timeout=10)
    parsed: dict[str, Any] = json.loads(reply.data)
    return parsed


@pytest.mark.parametrize("name", list(CASES))
async def test_a_request_missing_or_breaking_a_required_field_is_validation_failed(
    orders_host: Any, migrated_db: Any, name: str
) -> None:
    reply = await refused(orders_host.client, json.dumps(CASES[name]).encode())

    assert reply["code"] == "VALIDATION_FAILED", (name, reply)
    assert reply["message"].startswith("orders.create request is invalid:")
    assert "details" not in reply  # a wire-shape refusal names fields in the message only
    assert await orders_count(migrated_db.dsn) == 0


@pytest.mark.parametrize("name", list(RAW_BODIES))
async def test_a_body_that_is_not_a_json_request_is_validation_failed(
    orders_host: Any, migrated_db: Any, name: str
) -> None:
    reply = await refused(orders_host.client, RAW_BODIES[name])

    assert reply["code"] == "VALIDATION_FAILED", (name, reply)
    assert await orders_count(migrated_db.dsn) == 0


async def test_the_refusal_names_every_offending_field(orders_host: Any) -> None:
    body = GOOD | {"retailerCode": "", "currency": "eur", "lines": [line(quantity=0)]}

    reply = await refused(orders_host.client, json.dumps(body).encode())

    assert reply["code"] == "VALIDATION_FAILED"
    for field in ("retailerCode", "currency", "lines.0.quantity"):
        assert field in reply["message"], reply["message"]


async def test_a_valid_request_with_nobody_answering_the_stock_check_is_unavailable_not_validation(
    orders_host: Any,
) -> None:
    # The control the whole file rests on: past validation, THIS is what an unvalidated request
    # looks like with no stand-in subscribed. If this ever returned VALIDATION_FAILED the cases
    # above could no longer tell a validator from its absence.
    reply = await refused(orders_host.client, json.dumps(GOOD).encode())

    assert reply["code"] == "UNAVAILABLE"
