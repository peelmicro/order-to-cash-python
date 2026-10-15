# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Feature 28, acceptance item 3, through the composed fleet (`conftest.py`).

* R17 / SO-redelivery: an already-processed fact delivered AGAIN (the very bytes the broker holds,
  same key, so the same partition) changes nothing anywhere. The proof of "the consumer got past
  it" is a POSITIVE marker, never a sleep: behind each redelivery, on the same key and so the same
  partition, a fresh well-formed fact (a new `eventId`) is published; the saga's own
  `saga_ignored_facts` row for that `eventId` shows the partition advanced beyond the redelivery.
  Had the (`eventId`, consumer) guard been removed, the redelivered `order.placed.v1` would reach
  the status guard of a completed order and leave a `saga_ignored_facts` row of its own: the
  assertion counts the order's ignored rows, so it names exactly that.
* R16 / R29: a poisoned message (a valid envelope whose payload does not parse) is retried, then
  dead-lettered byte for byte by BOTH consumers of the topic (the saga and the projector), and the
  partition moves on: a valid fact published behind it on the same key is processed.
"""

import json
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

ORDERS = "otc.orders.facts.v1"
FULFILLMENT = "otc.fulfillment.facts.v1"


def with_fresh_event_id(record_value: bytes, **overrides: Any) -> tuple[uuid.UUID, bytes]:
    """A copy of a real envelope with a new `eventId` (and any envelope field overridden)."""
    envelope = json.loads(record_value)
    event_id = uuid.uuid4()
    envelope["eventId"] = str(event_id)
    envelope.update(overrides)
    return event_id, json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


async def footprint(fleet: Any, order_id: str, reference: str) -> dict[str, int]:
    """The rows every service holds for one order: the count of each, read from the databases."""
    uid = uuid.UUID(order_id)
    queries = {
        "orders.saga_commands": (
            "orders",
            "SELECT count(*) AS n FROM saga_commands WHERE order_id = $1",
            uid,
        ),
        "orders.outbox": (
            "orders",
            "SELECT count(*) AS n FROM outbox WHERE correlation_id = $1",
            uid,
        ),
        "fulfillment.reservations": (
            "fulfillment",
            "SELECT count(*) AS n FROM reservations WHERE order_reference = $1",
            reference,
        ),
        "fulfillment.despatches": (
            "fulfillment",
            "SELECT count(*) AS n FROM despatches WHERE order_reference = $1",
            reference,
        ),
        "fulfillment.outbox": (
            "fulfillment",
            "SELECT count(*) AS n FROM outbox WHERE correlation_id = $1",
            uid,
        ),
        "billing.invoices": (
            "billing",
            "SELECT count(*) AS n FROM invoices WHERE order_reference = $1",
            reference,
        ),
        "billing.payments": ("billing", "SELECT count(*) AS n FROM payments", None),
        "billing.outbox": (
            "billing",
            "SELECT count(*) AS n FROM outbox WHERE correlation_id = $1",
            uid,
        ),
    }
    counts: dict[str, int] = {}
    for name, (database, sql, argument) in queries.items():
        rows = await fleet.rows(database, sql, *([] if argument is None else [argument]))
        counts[name] = int(rows[0]["n"])
    return counts


async def ignored_event_ids(fleet: Any, order_id: str) -> list[str]:
    rows = await fleet.rows(
        "orders",
        "SELECT event_id FROM saga_ignored_facts WHERE correlation_id = $1",
        uuid.UUID(order_id),
    )
    return [str(r["event_id"]) for r in rows]


async def test_item3_an_already_processed_fact_delivered_again_changes_nothing_in_any_service(
    fleet: Any,
) -> None:
    placed = await fleet.place([{"productCode": "PRD-0002", "quantity": 3, "lineDiscount": 125}])
    assert placed.status_code == 201, placed.text
    order_id, reference = placed.json()["orderId"], placed.json()["orderReference"]
    await fleet.wait_status(order_id, "invoiced")
    assert (await fleet.pay(reference, "E2E-REDELIVER-1")).status_code == 201
    await fleet.wait_status(order_id, "completed")
    [placed_record] = [
        r for r in await fleet.records(ORDERS, order_id) if b"order.placed.v1" in r.value
    ]
    [reserved_record] = [
        r
        for r in await fleet.records(FULFILLMENT, order_id)
        if json.loads(r.value)["eventType"] == "stock.reserved.v1"
    ]
    # the saga has consumed everything it will: no row of it is owed
    before = await footprint(fleet, order_id, reference)
    ignored_before = await ignored_event_ids(fleet, order_id)
    assert ignored_before == [], "a clean run ignores no fact of its own order"

    # REDELIVERY: the very bytes, same key, so the same partition of each topic ...
    await fleet.produce(ORDERS, order_id.encode(), placed_record.value)
    await fleet.produce(FULFILLMENT, order_id.encode(), reserved_record.value)
    # ... and, behind each, a fresh fact on the same key: the POSITIVE marker of progress.
    marker_orders, orders_bytes = with_fresh_event_id(placed_record.value)
    marker_fulfillment, fulfillment_bytes = with_fresh_event_id(reserved_record.value)
    await fleet.produce(ORDERS, order_id.encode(), orders_bytes)
    await fleet.produce(FULFILLMENT, order_id.encode(), fulfillment_bytes)

    async def markers_seen() -> bool:
        return {str(marker_orders), str(marker_fulfillment)} <= set(
            await ignored_event_ids(fleet, order_id)
        )

    await fleet.eventually(
        markers_seen, "the saga reached both markers published behind the redeliveries"
    )
    # exactly the two markers were ignored: the redeliveries were absorbed by the (eventId, consumer) guard
    assert sorted(await ignored_event_ids(fleet, order_id)) == sorted(
        {str(marker_orders), str(marker_fulfillment)}
    ), (
        "a redelivered fact must be absorbed by the (eventId, consumer) guard: only the two markers are ignored"
    )
    assert await footprint(fleet, order_id, reference) == before
    assert await fleet.order_status(order_id) == "completed"


async def test_item3_a_poisoned_message_is_dead_lettered_byte_for_byte_by_both_consumers_and_the_partition_moves_on(
    fleet: Any,
) -> None:
    placed = await fleet.place([{"productCode": "PRD-0002", "quantity": 2, "lineDiscount": 10}])
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["orderId"]
    await fleet.wait_status(order_id, "invoiced")
    [real] = [r for r in await fleet.records(ORDERS, order_id) if b"order.placed.v1" in r.value]

    stranger = uuid.uuid4()  # an aggregate no service knows
    poison_id, poison = with_fresh_event_id(
        real.value,
        aggregateId=str(stranger),
        correlationId=str(stranger),
        payload={"orderReference": "ORD-POISON", "bogus": True},
    )
    valid_payload = {**json.loads(real.value)["payload"], "orderReference": "ORD-900001"}
    marker_id, marker = with_fresh_event_id(  # a valid fact of the stranger, its own reference
        real.value, aggregateId=str(stranger), correlationId=str(stranger), payload=valid_payload
    )
    await fleet.produce(ORDERS, str(stranger).encode(), poison)
    await fleet.produce(ORDERS, str(stranger).encode(), marker)  # behind the poison, same partition

    async def moved_on() -> bool:
        return str(marker_id) in await ignored_event_ids(fleet, str(stranger))

    await fleet.eventually(moved_on, "the saga processed the valid fact behind the poison")

    async def dead_letters() -> list[Any] | None:
        found = [
            r for r in await fleet.read_all(f"{ORDERS}.dlq") if r.key == str(stranger).encode()
        ]
        return found if len({r.headers["x-failed-consumer"] for r in found}) == 2 else None

    letters = await fleet.eventually(dead_letters, "both consumers dead-lettered the poison")
    assert sorted(r.headers["x-failed-consumer"].decode() for r in letters) == [
        "orders.saga",
        "projector",
    ]
    for letter in letters:
        assert letter.value == poison, "the dead letter is the original bytes"
        assert letter.headers["x-attempts"] == b"3"
        assert letter.headers["x-original-topic"] == ORDERS.encode()
        assert letter.event_id == str(poison_id)
    # the valid fact behind it was NOT dead-lettered by anybody
    assert [r for r in await fleet.read_all(f"{ORDERS}.dlq") if r.event_id == str(marker_id)] == []
