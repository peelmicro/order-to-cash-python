"""Acceptance 6 (plan line 967, json guard) and the timestamp read-back.

* `outbox.payload` returns, byte for byte, the text the application wrote through
  `otc_contracts.wire.to_wire_json` (the one serializer): key order, compactness and raw non-ASCII
  included. A `jsonb` column returns reordered, re-spaced text, so this test fails on it. The
  payload is `order.despatched.v1`, the fact this service emits.
* `timestamptz(3)` read-back: aware UTC, and a microsecond input comes back ROUNDED to the
  millisecond (.123987 -> .124), not truncated; measured in feature 9 and asserted again here for
  the `otc_fulfillment` columns (the wire formatter truncates, so the domain hands whole ms).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated.asyncapi import OrderDespatchedPayload
from otc_fulfillment.infrastructure.persistence.models import Outbox

pytestmark = pytest.mark.integration

GOLDEN = (
    Path(__file__).resolve().parents[4] / "tests/fixtures/golden_envelopes/order_despatched_v1.json"
)
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def _wire_payload() -> str:
    """The golden payload with a non-ASCII product code, written by the one serializer (declaration
    order, not alphabetical: a jsonb column would reorder it, so the order is visible)."""
    raw = json.loads(GOLDEN.read_text(encoding="utf-8"))["payload"]
    raw["lines"][0]["productCode"] = "PRD-Ñandú—€"
    model = from_wire_json(OrderDespatchedPayload, json.dumps(raw, ensure_ascii=False))
    return to_wire_json(model)


def _outbox(payload: str, occurred_at: datetime) -> Outbox:
    return Outbox(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        event_type="order.despatched.v1",
        aggregate_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        causation_id=uuid.uuid4(),
        payload=payload,
        occurred_at=occurred_at,
        created_at=NOW,
    )


async def test_outbox_payload_is_read_back_byte_identical(engine: AsyncEngine) -> None:
    payload = _wire_payload()
    assert "PRD-Ñandú—€" in payload  # raw, not \u-escaped
    keys = list(json.loads(payload))
    assert keys != sorted(keys)  # the serializer's declaration order, which jsonb would destroy
    assert ": " not in payload  # compact; jsonb would add a space after every `:` and `,`
    assert ", " not in payload
    async with AsyncSession(engine) as session, session.begin():
        session.add(_outbox(payload, NOW))
    async with AsyncSession(engine) as session:
        via_orm = (await session.execute(select(Outbox.payload))).scalar_one()
    async with engine.connect() as conn:
        via_sql = (await conn.execute(text("SELECT payload::text FROM outbox"))).scalar_one()
    assert via_orm.encode("utf-8") == payload.encode("utf-8")
    assert via_sql.encode("utf-8") == payload.encode("utf-8")


async def test_instants_come_back_aware_utc_and_rounded_to_the_millisecond(
    engine: AsyncEngine,
) -> None:
    micro = datetime(2026, 10, 5, 12, 0, 0, 123987, tzinfo=UTC)
    plus_two = micro.astimezone(timezone(timedelta(hours=2)))  # same instant, other offset
    assert plus_two.utcoffset() == timedelta(hours=2)
    async with AsyncSession(engine) as session, session.begin():
        session.add(_outbox("{}", plus_two))
    async with AsyncSession(engine) as session:
        back = (await session.execute(select(Outbox.occurred_at))).scalar_one()
    assert back.utcoffset() == timedelta(0)  # aware, UTC
    assert back == datetime(2026, 10, 5, 12, 0, 0, 124000, tzinfo=UTC)  # .123987 -> .124: rounds
