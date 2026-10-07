"""Wire parity of the published fact (feature 14, 4.14): OI15, R11 at the producer, the SA-2 note.

Three named assertions (#8 `design.md` 5.5), each a different claim:

1. *the relay changed nothing*: a row whose columns and payload TEXT come from #7's golden envelope,
   relayed to a real broker and consumed, equals the golden file BYTE FOR BYTE. This is a
   pass-through claim: it does not claim #9 reproduces MySQL's key order (the payload's key order
   is whatever the stored text had).
2. *the payload is semantically #7's*: a real `Order` placed with the golden business values has a
   stored payload equal to the golden payload under `strict_json_differences` (types strict, key
   order asserted nowhere).
3. *every published envelope is complete*: seven fields in declared order, none absent, null or
   empty.

Loop scope: default (function). A record is SELECTED by its own event id; "published" is read from
the broker.
"""

import importlib.util
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.infrastructure.outbox.payloads import narrow
from otc_orders.infrastructure.persistence.models import Outbox
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden_envelopes"
INSTANT = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)
ENVELOPE_KEYS = [
    "eventId",
    "eventType",
    "aggregateId",
    "correlationId",
    "causationId",
    "occurredAt",
    "payload",
]
ORDERS_GOLDENS = [
    "order_placed_v1.json",
    "order_confirmed_v1.json",
    "order_completed_v1.json",
    "order_cancelled_v1.json",  # its compensation summary holds an em dash: non-ASCII
]


def _load_strict_json() -> Any:
    path = REPO_ROOT / "packages" / "contracts" / "tests" / "strict_json.py"
    spec = importlib.util.spec_from_file_location("otc_orders_tests_strict_json", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strict_json_differences


strict_json_differences = _load_strict_json()


def split_at_payload(text: str) -> tuple[str, str]:
    head, _, rest = text.partition(',"payload":')
    assert rest.endswith("}"), "the payload is the last envelope field"
    return head, rest[:-1]


@pytest.mark.parametrize("golden", ORDERS_GOLDENS)
async def test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope(
    golden: str,
    row_planter: Any,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
) -> None:
    """A PASS-THROUGH claim: what the relay changed is nothing. Not a reproduction of #7's MySQL
    key order: the planted payload text is already in #7's order."""
    raw = (GOLDEN_DIR / golden).read_bytes()
    text = raw.decode("utf-8")
    document = json.loads(text)
    _, payload_text = split_at_payload(text)
    planted = await row_planter.plant(
        payload=payload_text,
        event_type=document["eventType"],
        occurred_at=datetime.fromisoformat(document["occurredAt"]),
        event_id=uuid.UUID(document["eventId"]),
        aggregate_id=uuid.UUID(document["aggregateId"]),
        correlation_id=uuid.UUID(document["correlationId"]),
        causation_id=uuid.UUID(document["causationId"]),
    )
    result = await make_relay(kafka_publisher).run_once()
    assert (result.claimed, result.published) == (1, 1)

    (record,) = [r for r in await read_topic() if r.event_id == planted.event_id]
    assert record.value == raw, f"{golden}: the consumed bytes differ from the golden file"
    assert record.key == str(planted.correlation_id).encode("utf-8")
    assert list(record.headers) == [
        ("x-event-type", document["eventType"].encode("utf-8")),
        ("content-type", b"application/json"),
    ], "exactly x-event-type and content-type"
    assert "traceparent" not in {name for name, _ in record.headers}, "no traceparent (feature 27)"


async def _insert_golden_references(dsn: str) -> None:
    currency_id = uuid.uuid4()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO currencies VALUES ($1, 'EUR', '978', 'E', 2, $2, $2)", currency_id, INSTANT
        )
        for table, code, gln in (
            ("retailers", "LeroyMerlinEs", "5400000000034"),
            ("companies", "PORTOTOOLS", "5400000000386"),
        ):
            await conn.execute(
                f"INSERT INTO {table} VALUES "  # noqa: S608
                "($1, $2, 'name', 'ES', 'VAT', $3, $4, NULL, $5, $5)",
                uuid.uuid4(),
                code,
                gln,
                currency_id,
                INSTANT,
            )
        await conn.execute(
            "INSERT INTO products VALUES ($1, 'PRD-0008', '5400000000799', 'p', 'd', 100, $2, "
            "NULL, $3, $3)",
            uuid.uuid4(),
            currency_id,
            INSTANT,
        )
    finally:
        await conn.close()


async def test_oi15_writer_stores_a_payload_semantically_equal_to_the_golden_for_the_same_business_inputs(  # noqa: E501
    uow: SqlAlchemyUnitOfWork, sessions: async_sessionmaker[AsyncSession], migrated_db: Any
) -> None:
    """The semantic half of OI15: same keys, same values, same types, same casing; key order is
    asserted nowhere (MySQL's `json` normalised it on #7's wire)."""
    await _insert_golden_references(migrated_db.dsn)
    text = (GOLDEN_DIR / "order_placed_v1.json").read_text(encoding="utf-8")
    document = json.loads(text)
    occurred_at = datetime.fromisoformat(document["occurredAt"])
    order = Order.place(
        order_reference=OrderNumber("ORD-000011"),
        order_date=occurred_at,
        retailer_code="LeroyMerlinEs",
        buyer_gln=GLN("5400000000034"),
        company_code="PORTOTOOLS",
        supplier_gln=GLN("5400000000386"),
        currency="EUR",
        lines=[
            OrderLineInput(
                product_code="PRD-0008",
                description="5L concentrated liquid laundry detergent",
                quantity=Quantity(6),
                unit_price=Money(1489, "EUR"),
                line_discount=Money(0, "EUR"),
            )
        ],
        notes=None,
        occurred_at=occurred_at,
        causation_id=UniqueId.parse(document["causationId"]),
    )
    async with uow.begin() as tx:
        await tx.orders.save(order)
    async with sessions() as session:
        stored = (await session.scalars(select(Outbox))).one()

    assert strict_json_differences(document["payload"], json.loads(stored.payload)) == []
    assert stored.causation_id == uuid.UUID(document["causationId"])
    assert stored.event_type == "order.placed.v1"


async def published_envelopes(
    uow: SqlAlchemyUnitOfWork,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
    orders: list[Order],
    event_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Any]:
    async with uow.begin() as tx:
        for order in orders:
            await tx.orders.save(order)
    await make_relay(kafka_publisher).run_once()
    wanted = set(event_ids)
    return {r.event_id: r for r in await read_topic() if r.event_id in wanted}


async def test_r11_published_envelope_carries_the_seven_fields_in_declared_order_with_none_absent_null_or_empty(  # noqa: E501
    uow: SqlAlchemyUnitOfWork,
    place_order: Any,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
) -> None:
    causes = [UniqueId.new() for _ in range(4)]
    confirmed: Order = place_order(
        order_reference="ORD-000031", occurred_at=INSTANT, causation_id=causes[0]
    )
    confirmed.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
    confirmed.approve_credit(occurred_at=INSTANT + timedelta(minutes=2))
    confirmed.confirm(occurred_at=INSTANT + timedelta(minutes=3), causation_id=causes[1])
    cancelled: Order = place_order(
        order_reference="ORD-000032", occurred_at=INSTANT, causation_id=causes[2]
    )
    cancelled.cancel(
        reason=CancellationReason.OPERATOR_CANCELLED,
        compensation_steps=[],
        occurred_at=INSTANT + timedelta(minutes=4),
        causation_id=causes[3],
        note="n",
    )
    expected = {
        narrow(e).event_id.value: (order, narrow(e).causation_id.value)
        for order in (confirmed, cancelled)
        for e in order.domain_events
    }
    assert len(expected) == 4
    found = await published_envelopes(
        uow, make_relay, kafka_publisher, read_topic, [confirmed, cancelled], list(expected)
    )
    assert set(found) == set(expected), "every fact reached the broker"
    for event_id, record in found.items():
        order, cause = expected[event_id]
        envelope = json.loads(record.value)
        assert list(envelope) == ENVELOPE_KEYS, "declared order, none absent"
        for key in ENVELOPE_KEYS:
            assert envelope[key] not in (None, "", {}, []), f"{key} is null or empty"
        assert envelope["correlationId"] == envelope["aggregateId"] == str(order.id)
        assert envelope["causationId"] == str(cause)
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", envelope["occurredAt"])
        assert re.fullmatch(r"[a-z]+\.[a-z_]+\.v[0-9]+", envelope["eventType"])
        assert dict(record.headers)["x-event-type"] == envelope["eventType"].encode("utf-8")


NOTE = 'Stock rejected: 3 \u00d7 “PRD-1” unavailable — retry, ñandú \\ "quoted" \u2603'


async def cancel_and_publish(
    uow: SqlAlchemyUnitOfWork,
    place_order: Any,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
    note: str | None,
    reference: str,
) -> Any:
    order: Order = place_order(order_reference=reference, occurred_at=INSTANT)
    order.cancel(
        reason=CancellationReason.STOCK_REJECTED,
        compensation_steps=[],
        occurred_at=INSTANT + timedelta(minutes=1),
        causation_id=UniqueId.new(),
        note=note,
    )
    cancelled_event = narrow(order.domain_events[-1]).event_id.value
    found = await published_envelopes(
        uow, make_relay, kafka_publisher, read_topic, [order], [cancelled_event]
    )
    return found[cancelled_event]


async def test_sa2_published_cancelled_envelope_carries_the_note_with_the_exact_supplied_text(
    uow: SqlAlchemyUnitOfWork,
    place_order: Any,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
) -> None:
    record = await cancel_and_publish(
        uow, place_order, make_relay, kafka_publisher, read_topic, NOTE, "ORD-000041"
    )
    envelope = json.loads(record.value)
    assert envelope["eventType"] == "order.cancelled.v1"
    assert envelope["payload"]["note"] == NOTE, "the exact supplied text"
    assert "ñandú".encode() in record.value, "non-ASCII written raw, not as \\u escapes"


async def test_sa2_published_cancelled_envelope_omits_the_note_key_when_none_was_supplied(
    uow: SqlAlchemyUnitOfWork,
    place_order: Any,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
) -> None:
    record = await cancel_and_publish(
        uow, place_order, make_relay, kafka_publisher, read_topic, None, "ORD-000042"
    )
    payload = json.loads(record.value)["payload"]
    assert "note" not in payload, "an absent note is an absent key, never an explicit null"
    assert payload["cancellationReason"] == "stock_rejected"
