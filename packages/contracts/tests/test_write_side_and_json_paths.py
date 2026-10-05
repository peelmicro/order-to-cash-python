"""Fix round 1 (review D1, D2, D7): every way a model reaches bytes obeys the one configuration.

D1 write side: an instance can be mutated or built past validation (`model_copy(update=...)`,
`model_construct`); `to_wire_json` re-validates and refuses it, naming the field, and assignment is
refused outright (`frozen=True`).

D2 one instant format: `model_dump_json()`, `model_dump(mode="json")` and a FastAPI `response_model`
write `.mmmZ` too, not Pydantic's `.442000Z`.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from otc_contracts import parse_fact, to_wire_json
from otc_contracts.generated import openapi
from otc_contracts.generated.asyncapi import Money, OrderPlacedEvent
from otc_contracts.generated.openapi import OrderReferences

GOLDEN_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "golden_envelopes"
GOLDENS = sorted(GOLDEN_DIR.glob("*.json"))
SUB_MS = datetime(2026, 8, 30, 16, 20, 20, 442999, tzinfo=UTC)


def good() -> Money:
    return Money(amount=8934, currency="EUR")


# ------------------------------------------------------------------ D1: assignment is refused
def test_assignment_to_a_wire_model_is_refused() -> None:
    money = good()
    with pytest.raises(ValidationError, match="frozen_instance"):
        money.amount = True
    assert money.amount == 8934


# ----------------------------------------------- D1: model_copy(update=...) is refused at write
@pytest.mark.parametrize("bad", [True, 89.34, 8934.0, "8934", 2**63])
def test_a_copy_updated_past_validation_is_refused_at_write_naming_the_field(bad: object) -> None:
    copied = good().model_copy(update={"amount": bad})
    with pytest.raises(ValidationError, match="amount"):
        to_wire_json(copied)


def test_a_copy_with_a_bad_uuid_or_an_unformatted_instant_is_refused_at_write() -> None:
    event = parse_fact(GOLDENS[0].read_text("utf-8"))
    with pytest.raises(ValidationError, match="aggregateId"):
        to_wire_json(event.model_copy(update={"aggregate_id": "not-a-uuid"}))
    with pytest.raises(ValidationError, match="occurredAt"):
        to_wire_json(event.model_copy(update={"occurred_at": "2026-08-30T16:20:20.442000Z"}))


# ----------------------------------------------------- D1: model_construct is refused at write
@pytest.mark.parametrize("bad", [True, 89.34, "8934"])
def test_a_constructed_model_that_skipped_validation_is_refused_at_write(bad: object) -> None:
    constructed = Money.model_construct(amount=bad, currency="EUR")
    with pytest.raises(ValidationError, match="amount"):
        to_wire_json(constructed)


def test_a_valid_instance_still_writes() -> None:
    assert to_wire_json(good()) == '{"amount":8934,"currency":"EUR"}'
    assert to_wire_json(good().model_copy(update={"amount": 1})) == '{"amount":1,"currency":"EUR"}'


# --------------------------------------------------------------- D2: every JSON path writes .mmmZ
@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.name)
def test_model_dump_json_equals_to_wire_json_on_every_golden(path: Path) -> None:
    event = parse_fact(path.read_text("utf-8"))
    assert event.model_dump_json() == to_wire_json(event)


def test_model_dump_mode_json_writes_the_wire_instant() -> None:
    event = parse_fact((GOLDEN_DIR / "order_placed_v1.json").read_text("utf-8"))
    assert isinstance(event, OrderPlacedEvent)
    moved = event.model_copy(update={"occurred_at": SUB_MS})
    assert moved.model_dump(mode="json")["occurredAt"] == "2026-08-30T16:20:20.442Z"
    # nested models too: the order date inside the payload
    nested = moved.payload.model_copy(update={"order_date": SUB_MS})
    assert nested.model_dump(mode="json")["orderDate"] == "2026-08-30T16:20:20.442Z"
    # python mode is unchanged: datetimes stay objects for the writer
    assert moved.model_dump()["occurredAt"] == SUB_MS


def test_an_openapi_model_writes_the_wire_instant_through_model_dump_json() -> None:
    assert openapi.StreamPing(at=SUB_MS).model_dump_json() == '{"at":"2026-08-30T16:20:20.442Z"}'


async def test_a_fastapi_response_model_writes_the_wire_instant() -> None:
    app = FastAPI()
    golden = parse_fact((GOLDEN_DIR / "order_placed_v1.json").read_text("utf-8"))
    assert isinstance(golden, OrderPlacedEvent)

    @app.get("/ping", response_model=openapi.StreamPing)
    def ping() -> openapi.StreamPing:
        return openapi.StreamPing(at=SUB_MS)

    @app.get("/fact", response_model=OrderPlacedEvent)
    def fact() -> OrderPlacedEvent:
        return golden

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        ping_response = await client.get("/ping")
        fact_response = await client.get("/fact")
    assert ping_response.text == '{"at":"2026-08-30T16:20:20.442Z"}'
    body = json.loads(fact_response.text)
    assert body["occurredAt"] == "2026-08-30T16:20:20.442Z"
    assert body["payload"]["orderDate"] == "2026-08-30T16:20:20.442Z"


# ------------------------------------------------------ D7: nullable lookup follows the MRO
def test_a_subclass_declared_elsewhere_keeps_the_explicit_nulls() -> None:
    class GatewayReferences(OrderReferences):
        pass

    assert GatewayReferences().model_dump_json() == (
        '{"despatchReference":null,"invoiceReference":null,"paymentReference":null}'
    )


def test_uuid_fields_stay_uuid_objects_in_python_mode() -> None:
    event = parse_fact((GOLDEN_DIR / "order_placed_v1.json").read_text("utf-8"))
    assert isinstance(event.model_dump()["eventId"], UUID)
