"""Plan line 967 (json guard) and the timestamp read-back (unit: bytes of a payload / one instant).

* `outbox.payload` and `saga_commands.payload` return, byte for byte, the text the application wrote
  through `otc_contracts.wire.to_wire_json` (the one serializer): key order, compactness and raw
  non-ASCII included. A `jsonb` column returns reordered, re-spaced text, so this test fails on it.
* `timestamptz(3)` read-back: values come back timezone-aware UTC, and a microsecond input comes
  back ROUNDED to the millisecond (measured below: .123987 -> .124), not truncated. The wire
  formatter (`format_instant`) truncates, so the engine's rounding and the wire's truncation differ
  for a sub-millisecond input; the domain should hand the database whole milliseconds. Asserted,
  not assumed.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated.asyncapi import OrderPlacedPayload
from otc_orders.infrastructure.persistence.models import Outbox, SagaCommand

pytestmark = pytest.mark.integration

GOLDEN = (
    Path(__file__).resolve().parents[4] / "tests/fixtures/golden_envelopes/order_placed_v1.json"
)
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def _wire_payload() -> str:
    """The golden payload with a non-ASCII description, written by the one serializer.

    The serializer writes keys in the spec's declaration order (`orderReference`, `retailerCode`,
    ... `lines` ...), which is not alphabetical, and a jsonb column would reorder them, so the order
    is part of what the test can see.
    """
    raw = json.loads(GOLDEN.read_text(encoding="utf-8"))["payload"]
    raw["lines"][0]["description"] = "Détergent 5L — ñandú €"
    model = from_wire_json(OrderPlacedPayload, json.dumps(raw, ensure_ascii=False))
    return to_wire_json(model)


async def test_outbox_payload_is_read_back_byte_identical(engine: AsyncEngine) -> None:
    payload = _wire_payload()
    assert "Détergent 5L — ñandú €" in payload  # raw, not \u-escaped
    keys = list(json.loads(payload))
    assert keys != sorted(keys)  # the serializer's declaration order, which jsonb would destroy
    # compact; jsonb would add a space after every `:` and `,`
    assert ": " not in payload
    assert ", " not in payload
    row_id = uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            Outbox(
                id=row_id,
                event_id=uuid.uuid4(),
                event_type="order.placed.v1",
                aggregate_id=uuid.uuid4(),
                correlation_id=uuid.uuid4(),
                causation_id=uuid.uuid4(),
                payload=payload,
                occurred_at=NOW,
                created_at=NOW,
            )
        )
    async with AsyncSession(engine) as session:
        via_orm = (await session.execute(select(Outbox.payload))).scalar_one()
    async with engine.connect() as conn:
        via_sql = (await conn.execute(text("SELECT payload::text FROM outbox"))).scalar_one()
    assert via_orm.encode("utf-8") == payload.encode("utf-8")
    assert via_sql.encode("utf-8") == payload.encode("utf-8")


async def test_saga_command_payload_is_read_back_byte_identical(engine: AsyncEngine) -> None:
    payload = '{"zeta":1,"alpha":{"b":"ñ","a":[1,2]},"orderReference":"ORD-000001"}'
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            SagaCommand(
                id=uuid.uuid4(),
                order_id=uuid.uuid4(),
                order_reference="ORD-000001",
                command="stock.reserve",
                payload=payload,
                triggering_event_id=uuid.uuid4(),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    async with engine.connect() as conn:
        back = (await conn.execute(text("SELECT payload::text FROM saga_commands"))).scalar_one()
    assert back.encode("utf-8") == payload.encode("utf-8")


async def test_instants_come_back_aware_utc_and_rounded_to_the_millisecond(
    engine: AsyncEngine,
) -> None:
    micro = datetime(2026, 10, 5, 12, 0, 0, 123987, tzinfo=UTC)
    plus_two = micro.astimezone(timezone(timedelta(hours=2)))  # same instant, other offset
    assert plus_two.utcoffset() == timedelta(hours=2)
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            Outbox(
                id=uuid.uuid4(),
                event_id=uuid.uuid4(),
                event_type="order.placed.v1",
                aggregate_id=uuid.uuid4(),
                correlation_id=uuid.uuid4(),
                causation_id=uuid.uuid4(),
                payload="{}",
                occurred_at=plus_two,
                created_at=NOW,
            )
        )
    async with AsyncSession(engine) as session:
        back = (await session.execute(select(Outbox.occurred_at))).scalar_one()
    assert back.tzinfo is not None
    assert back.utcoffset() == timedelta(0)  # the session time zone is UTC: aware, UTC
    assert back == datetime(2026, 10, 5, 12, 0, 0, 124000, tzinfo=UTC)  # .123987 -> .124: rounds
