"""`catalog.reference.list` over real NATS against the REAL Orders host and a real PostgreSQL
(feature 40). The caller is a plain NATS client; what the Gateway sends is proved separately, by
the real Gateway, in `test_catalog_through_gateway.py`.

Every request field is observed to change the reply: `kinds` (which keys exist), `includeDisabled`
(the disabled row of each kind appears), and the ordering of every list (the fixture's insertion
order differs from code order and from its reverse).
"""

import json
from typing import Any

import pytest
import pytest_asyncio
from nats.aio.client import Client as NatsClient

pytestmark = pytest.mark.integration

SUBJECT = "catalog.reference.list"
KINDS = ("products", "retailers", "companies", "currencies")


async def ask(client: NatsClient, payload: dict[str, Any] | bytes | None) -> dict[str, Any]:
    body = (
        b""
        if payload is None
        else payload
        if isinstance(payload, bytes)
        else json.dumps(payload).encode()
    )
    reply = await client.request(SUBJECT, body, timeout=10)
    document: dict[str, Any] = json.loads(reply.data)
    return document


@pytest_asyncio.fixture(loop_scope="function")  # the host lives and dies in the test's loop
async def host(orders_host_factory: Any, catalog_data: Any) -> Any:
    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false") as running:
        yield running


async def test_kinds_omitted_returns_the_four_collections_enabled_rows_only(
    host: Any, catalog_data: Any
) -> None:
    reply = await ask(host.client, {})

    assert set(reply) == set(KINDS)
    for kind in KINDS:
        assert reply[kind] == catalog_data.listed(kind, include_disabled=False), kind


async def test_an_absent_body_is_the_same_as_an_empty_object(host: Any, catalog_data: Any) -> None:
    assert await ask(host.client, None) == await ask(host.client, {})


@pytest.mark.parametrize("kind", KINDS)
async def test_only_the_requested_kind_is_present_in_the_reply(
    host: Any, catalog_data: Any, kind: str
) -> None:
    reply = await ask(host.client, {"kinds": [kind]})

    assert list(reply) == [kind]
    assert reply[kind] == catalog_data.listed(kind, include_disabled=False)


async def test_two_kinds_return_those_two_and_no_other(host: Any, catalog_data: Any) -> None:
    reply = await ask(host.client, {"kinds": ["currencies", "retailers"]})

    assert set(reply) == {"currencies", "retailers"}


@pytest.mark.parametrize("kind", ["products", "retailers", "companies"])
async def test_include_disabled_true_adds_the_disabled_row_marked_not_enabled(
    host: Any, catalog_data: Any, kind: str
) -> None:
    without = await ask(host.client, {"kinds": [kind], "includeDisabled": False})
    default = await ask(host.client, {"kinds": [kind]})
    with_disabled = await ask(host.client, {"kinds": [kind], "includeDisabled": True})

    assert without == default
    assert [row["enabled"] for row in without[kind]] == [True, True, True]
    assert [row["enabled"] for row in with_disabled[kind]] == [True, True, True, False]
    assert with_disabled[kind] == catalog_data.listed(kind, include_disabled=True)


async def test_include_disabled_changes_nothing_for_currencies(
    host: Any, catalog_data: Any
) -> None:
    reply = await ask(host.client, {"kinds": ["currencies"], "includeDisabled": True})

    assert reply["currencies"] == catalog_data.currencies


@pytest.mark.parametrize("kind", KINDS)
async def test_every_list_is_ordered_by_code_not_by_insertion_or_its_reverse(
    host: Any, catalog_data: Any, kind: str
) -> None:
    reply = await ask(host.client, {"kinds": [kind], "includeDisabled": True})

    codes = [row["code"] for row in reply[kind]]
    assert codes == sorted(codes)
    assert codes == [row["code"] for row in catalog_data.listed(kind, include_disabled=True)]


async def test_prices_are_integer_minor_units_and_the_reply_is_compact_utf8(
    host: Any, catalog_data: Any
) -> None:
    raw = (
        await host.client.request(SUBJECT, b'{"kinds":["products","currencies"]}', timeout=10)
    ).data

    document = json.loads(raw)
    assert [type(p["price"]) for p in document["products"]] == [int, int, int]
    assert raw == json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert "CE€".encode() in raw  # non-ASCII written raw, not €


@pytest.mark.parametrize(
    "payload",
    [
        {"kinds": []},
        {"kinds": ["gadgets"]},
        {"kinds": "products"},
        {"includeDisabled": "yes"},
        b"[1]",
        b"null",
        b"not json",
    ],
)
async def test_a_malformed_request_is_answered_validation_failed_never_left_unanswered(
    host: Any, catalog_data: Any, payload: Any
) -> None:
    reply = await ask(host.client, payload)

    assert reply["code"] == "VALIDATION_FAILED"
    assert reply["occurredAt"].endswith("Z")
    assert "message" in reply


async def test_orders_create_still_answers_on_the_same_responder(
    host: Any, catalog_data: Any
) -> None:
    reply = await ask_create(host.client)

    assert (
        reply["code"] == "VALIDATION_FAILED"
    )  # the empty request is refused by ITS own validation


async def ask_create(client: NatsClient) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (await client.request("orders.create", b"{}", timeout=10)).data
    )
    return document
