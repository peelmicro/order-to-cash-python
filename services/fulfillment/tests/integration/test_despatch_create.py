"""`fulfillment.despatch.create` through the real host (R36; F6, F7, F8): what a caller can observe.

The order is reserved through the real `stock.reserve` responder first, so the despatch consumes
reservations the service itself created. Every negative assertion has a control in the same test
(a refusal that writes nothing is paired with a request that does write, so an empty read means
something).
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_contracts import from_wire_json
from otc_contracts.generated import asyncapi

COMPANY = "ACME-CO"
RETAILER = "RET-9"
ORDER = "ORD-000042"
RESERVE_HEADERS = {
    "x-correlation-id": str(uuid.UUID(int=0xC0C0)),
    "x-request-id": str(uuid.UUID(int=0xCA05)),
}
DESPATCH_CORRELATION = str(uuid.UUID(int=0xD0D0))
DESPATCH_REQUEST = str(uuid.UUID(int=0xDA05))
DESPATCH_HEADERS = {"x-correlation-id": DESPATCH_CORRELATION, "x-request-id": DESPATCH_REQUEST}
DESPATCH = "fulfillment.despatch.create"
FORBIDDEN = {"response", "isDisposed", "id"}


def reserve_body(*lines: tuple[str, int], order: str = ORDER) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "lines": [{"productCode": code, "units": units} for code, units in lines],
    }


def despatch_body(order: str = ORDER) -> dict[str, Any]:
    return {"orderReference": order}


async def reserved_order(db: Any, rpc: Any) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = await db.seed_stock(
        COMPANY, [("PRD-A1", 10, 1, 3), ("PRD-B2", 20, 2, 3)]
    )
    first = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 3), ("PRD-B2", 5)),
        headers=RESERVE_HEADERS,
    )
    assert first["outcome"] == "accepted"
    return ids


def facts_of(outbox: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [row for row in outbox if row["event_type"] == event_type]


async def stock_rows(db: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]


async def table_count(db: Any, table: str) -> int:
    [row] = await db.fetch(f"SELECT count(*) AS n FROM {table}")  # noqa: S608 - a literal name
    return int(row["n"])


async def next_value(db: Any) -> int | None:
    rows = await db.fetch("SELECT next_value FROM despatch_number_sequences WHERE id = 1")
    return int(rows[0]["next_value"]) if rows else None


async def test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    ids = await reserved_order(db, rpc)
    before = datetime.now(UTC)

    reply = await rpc(DESPATCH, despatch_body(), headers=DESPATCH_HEADERS)

    after = datetime.now(UTC)
    # the reply
    [advice] = await db.fetch("SELECT * FROM despatches")
    items = await db.fetch(
        "SELECT * FROM despatch_items WHERE despatch_id = $1 ORDER BY product_code", advice["id"]
    )
    assert reply == {
        "orderReference": ORDER,
        "despatchReference": "DES-000001",
        "despatchDate": reply["despatchDate"],
        "created": True,
        "lines": [{"productCode": "PRD-A1", "units": 3}, {"productCode": "PRD-B2", "units": 5}],
    }
    reply_date = datetime.fromisoformat(reply["despatchDate"])
    assert before.replace(microsecond=0) <= reply_date <= after, "the clock instant, bracketed"
    # the advice and its lines
    assert advice["despatch_reference"] == "DES-000001"
    assert advice["order_reference"] == ORDER
    assert (advice["company_code"], advice["retailer_code"]) == (COMPANY, RETAILER)
    assert advice["despatch_date"] == reply_date
    assert [(i["product_code"], i["units"]) for i in items] == [("PRD-A1", 3), ("PRD-B2", 5)]
    # F7: every line traces to a reservation of the order that is now `consumed`, with its units
    reservations = await db.reservations(ORDER)
    assert {r["status"] for r in reservations} == {"consumed"}
    assert sorted((r["product_code"], r["units"]) for r in reservations) == [
        (i["product_code"], i["units"]) for i in items
    ]
    # BOTH counters fell by the consumed units: on-hand 10 -> 7 and 20 -> 15, reserved (1 + 3) -> 1
    # and (2 + 5) -> 2
    a1, b2 = await db.stock(COMPANY, "PRD-A1"), await db.stock(COMPANY, "PRD-B2")
    assert (a1["units"], a1["reserved_units"]) == (7, 1)
    assert (b2["units"], b2["reserved_units"]) == (15, 2)
    assert await next_value(db) == 2, "one number was allocated"
    # the fact: exactly one, the advice's, with the request's ids
    outbox = await db.outbox()
    facts = facts_of(outbox, "order.despatched.v1")
    assert len(facts) == 1, "exactly one order.despatched.v1 in the outbox"
    [fact] = facts
    assert len(outbox) == 2, "the reserve's own fact and this one: the despatch wrote no stock fact"
    assert len(facts_of(outbox, "stock.reserved.v1")) == 1, "control: the outbox read sees rows"
    assert fact["aggregate_id"] == advice["id"], "the advice's own id, not a stock item's"
    assert advice["id"] not in ids.values()
    assert str(fact["correlation_id"]) == DESPATCH_CORRELATION
    assert str(fact["causation_id"]) == DESPATCH_REQUEST
    assert fact["occurred_at"] == reply_date
    assert fact["payload"] == {
        "orderReference": ORDER,
        "despatchReference": "DES-000001",
        "despatchDate": reply["despatchDate"],
        "companyCode": COMPANY,
        "retailerCode": RETAILER,
        "lines": [{"productCode": "PRD-A1", "units": 3}, {"productCode": "PRD-B2", "units": 5}],
    }


async def test_r36_an_order_that_holds_no_reservation_creates_no_advice_burns_no_number_and_emits_nothing(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 1, 3), ("PRD-B2", 20, 2, 3)])
    stock_before = await stock_rows(db)

    reply = await rpc(DESPATCH, despatch_body(), headers=DESPATCH_HEADERS)

    assert reply["code"] == "PRECONDITION_FAILED"
    assert reply["details"] == {"orderReference": ORDER}
    assert reply["correlationId"] == DESPATCH_CORRELATION
    assert await table_count(db, "despatches") == 0
    assert await table_count(db, "despatch_items") == 0
    assert await db.outbox() == []
    assert await stock_rows(db) == stock_before
    assert await next_value(db) is None, "not even the counter row was seeded"
    # control row: the same order, once reserved, DOES despatch, and gets the FIRST number
    first = await rpc(
        "fulfillment.stock.reserve", reserve_body(("PRD-A1", 3)), headers=RESERVE_HEADERS
    )
    assert first["outcome"] == "accepted"
    created = await rpc(DESPATCH, despatch_body(), headers=DESPATCH_HEADERS)
    assert created["created"] is True
    assert created["despatchReference"] == "DES-000001"
    assert len(facts_of(await db.outbox(), "order.despatched.v1")) == 1


async def test_r36_an_order_whose_reservations_were_all_released_creates_no_advice_and_emits_no_despatch_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)
    await rpc(
        "fulfillment.stock.release",
        {"orderReference": ORDER, "reason": "order_cancelled"},
        headers={
            "x-correlation-id": str(uuid.UUID(int=0xE0)),
            "x-request-id": str(uuid.UUID(int=0xE1)),
        },
    )
    stock_before = await stock_rows(db)
    reservations_before = [dict(r) for r in await db.reservations(ORDER)]

    reply = await rpc(DESPATCH, despatch_body(), headers=DESPATCH_HEADERS)

    assert reply["code"] == "PRECONDITION_FAILED"
    assert reply["details"] == {"orderReference": ORDER}
    assert await table_count(db, "despatches") == 0
    assert await stock_rows(db) == stock_before, "released stock stays released"
    assert [dict(r) for r in await db.reservations(ORDER)] == reservations_before
    outbox = await db.outbox()
    assert facts_of(outbox, "order.despatched.v1") == []
    assert {r["event_type"] for r in outbox} == {"stock.reserved.v1", "stock.released.v1"}, (
        "control: the outbox read sees the two facts that were written"
    )
    assert await next_value(db) is None


async def test_f8_a_repeated_despatch_returns_the_existing_advice_changes_nothing_and_emits_no_second_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)
    first = await rpc(DESPATCH, despatch_body(), headers=DESPATCH_HEADERS)
    stock_before = await stock_rows(db)
    reservations_before = [dict(r) for r in await db.reservations(ORDER)]
    outbox_before = await db.outbox()
    again_headers = {
        "x-correlation-id": str(uuid.UUID(int=0xE0)),
        "x-request-id": str(uuid.UUID(int=0xE1)),
    }

    again = await rpc(DESPATCH, despatch_body(), headers=again_headers)

    assert first["created"] is True
    assert again == {**first, "created": False}, "the same reference, date and lines, in order"
    assert await table_count(db, "despatches") == 1
    assert await table_count(db, "despatch_items") == 2
    assert await stock_rows(db) == stock_before
    assert [dict(r) for r in await db.reservations(ORDER)] == reservations_before
    outbox = await db.outbox()
    assert outbox == outbox_before, "no second fact, nothing re-stamped"
    assert len(facts_of(outbox, "order.despatched.v1")) == 1, "control: the first fact is there"
    assert all(str(r["correlation_id"]) != again_headers["x-correlation-id"] for r in outbox)
    assert await next_value(db) == 2, "the repeat allocated no number"


async def test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)
    first_request, second_request = str(uuid.UUID(int=0xA1)), str(uuid.UUID(int=0xA2))
    hold = await db.hold([(COMPANY, "PRD-A1")])  # both requests pass the fast path, then queue
    try:
        calls = {
            request: asyncio.create_task(
                rpc(
                    DESPATCH,
                    despatch_body(),
                    headers={"x-correlation-id": DESPATCH_CORRELATION, "x-request-id": request},
                    timeout=30,
                )
            )
            for request in (first_request, second_request)
        }
        try:
            await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 2, deadline_seconds=10)
        except TimeoutError:
            pytest.fail(
                "the two despatches never both waited on the held stock row: the pair did not"
                " overlap, so this test would prove nothing about F8's race"
            )
        assert not any(task.done() for task in calls.values())
        await hold.commit()
        replies = {
            request: await asyncio.wait_for(task, timeout=15) for request, task in calls.items()
        }
    finally:
        await hold.rollback()

    created = [request for request, reply in replies.items() if reply.get("created") is True]
    repeated = [request for request, reply in replies.items() if reply.get("created") is False]
    assert len(created) == 1, f"exactly one creates: {replies}"
    assert len(repeated) == 1, f"exactly one repeats: {replies}"
    assert {k: v for k, v in replies[created[0]].items() if k != "created"} == {
        k: v for k, v in replies[repeated[0]].items() if k != "created"
    }, "both answer with the one advice"
    assert await table_count(db, "despatches") == 1
    assert await table_count(db, "despatch_items") == 2
    outbox = await db.outbox()
    [fact] = facts_of(outbox, "order.despatched.v1")
    assert str(fact["causation_id"]) == created[0], "the fact is the creating request's"
    assert await next_value(db) == 2, "exactly one number was allocated"
    assert {r["status"] for r in await db.reservations(ORDER)} == {"consumed"}


async def test_fs3_a_despatch_without_the_correlation_headers_is_refused_and_writes_nothing(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await reserved_order(db, rpc)

    reply = await rpc(DESPATCH, despatch_body())

    assert reply["code"] == "VALIDATION_FAILED"
    assert await table_count(db, "despatches") == 0
    assert {r["status"] for r in await db.reservations(ORDER)} == {"reserved"}
    # control: with the headers the same request despatches
    assert (await rpc(DESPATCH, despatch_body(), headers=DESPATCH_HEADERS))["created"] is True


async def test_fs4_the_despatch_reply_is_a_bare_compact_json_payload_that_parses_as_its_model(
    fulfillment_host: Any, db: Any, nats_client: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])
    await nats_client.request(
        "fulfillment.stock.reserve",
        json.dumps(reserve_body(("PRD-A1", 2))).encode(),
        timeout=15,
        headers=RESERVE_HEADERS,
    )

    message = await nats_client.request(
        DESPATCH, json.dumps(despatch_body()).encode(), timeout=15, headers=DESPATCH_HEADERS
    )

    reply = json.loads(message.data)
    assert set(reply) == {"orderReference", "despatchReference", "despatchDate", "created", "lines"}
    assert FORBIDDEN.isdisjoint(reply), "no packet envelope around the reply"
    text = message.data.decode("utf-8")
    assert text == json.dumps(reply, separators=(",", ":"), ensure_ascii=False)
    assert reply["despatchDate"].endswith("Z")
    assert len(reply["despatchDate"]) == len("2026-10-08T09:30:05.123Z")
    from_wire_json(asyncapi.DespatchCreateReplyPayload, message.data)  # strict parse
    # and an error is a bare RpcError too
    refused = await nats_client.request(
        DESPATCH,
        json.dumps({"orderReference": "ORD-000099"}).encode(),
        timeout=15,
        headers=DESPATCH_HEADERS,
    )
    error = from_wire_json(asyncapi.RpcError, refused.data)
    assert error.code is asyncapi.Code.precondition_failed
