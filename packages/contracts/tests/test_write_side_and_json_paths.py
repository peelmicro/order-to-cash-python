"""Fix round 1 (review D1, D2, D7): every way a model reaches bytes obeys the one configuration.

D1 write side: an instance can be mutated or built past validation (`model_copy(update=...)`,
`model_construct`); `to_wire_json` re-validates and refuses it, naming the field, and assignment is
refused outright (`frozen=True`).

Round 2 (backlog 203, review R2-1..R2-4): the validation refusal now holds on EVERY JSON path
(`model_dump_json`, `model_dump(mode="json")`, a FastAPI `response_model`), and the `.mmmZ` instant
holds for a list-held and a dict-held datetime.

D2 one instant format: `model_dump_json()`, `model_dump(mode="json")` and a FastAPI `response_model`
write `.mmmZ` too, not Pydantic's `.442000Z`.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import AwareDatetime, ValidationError
from pydantic_core import PydanticSerializationError

from otc_contracts import WireModel, parse_fact, to_wire_json
from otc_contracts.generated import openapi
from otc_contracts.generated.asyncapi import Envelope, Money, OrderPlacedEvent
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


# ------------------------------------------- R2-1: every JSON path refuses an unvalidated instance
# Pydantic wraps an exception raised inside a serializer: the refusal arrives as a
# PydanticSerializationError whose message carries the ValidationError text, naming the field.
BAD_AMOUNTS = [True, 89.34, "8934"]


def _json_paths(model: WireModel) -> dict[str, Any]:
    return {
        "model_dump_json": model.model_dump_json,
        "model_dump(mode=json)": lambda: model.model_dump(mode="json"),
    }


@pytest.mark.parametrize("bad", BAD_AMOUNTS, ids=repr)
@pytest.mark.parametrize("path", ["model_dump_json", "model_dump(mode=json)"])
def test_r2_1_a_copy_updated_past_validation_is_refused_by_every_json_path(
    path: str, bad: object
) -> None:
    copied = good().model_copy(update={"amount": bad})
    with pytest.raises(PydanticSerializationError, match="amount"):
        _json_paths(copied)[path]()


@pytest.mark.parametrize("bad", BAD_AMOUNTS, ids=repr)
@pytest.mark.parametrize("path", ["model_dump_json", "model_dump(mode=json)"])
def test_r2_1_a_constructed_model_is_refused_by_every_json_path(path: str, bad: object) -> None:
    constructed = Money.model_construct(amount=bad, currency="EUR")
    with pytest.raises(PydanticSerializationError, match="amount"):
        _json_paths(constructed)[path]()


def test_r2_1_a_nested_unvalidated_field_is_refused_by_the_parents_json_path() -> None:
    event = parse_fact((GOLDEN_DIR / "order_placed_v1.json").read_text("utf-8"))
    assert isinstance(event, OrderPlacedEvent)
    broken = event.model_copy(
        update={"payload": event.payload.model_copy(update={"total_amount": 89.34})}
    )
    with pytest.raises(PydanticSerializationError, match="totalAmount"):
        broken.model_dump_json()


async def test_r2_1_a_fastapi_response_model_refuses_an_unvalidated_instance() -> None:
    app = FastAPI()

    @app.get("/money", response_model=Money)
    def money() -> Money:
        return Money.model_construct(amount=89.34, currency="EUR")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/money")
    assert response.status_code == 500
    assert "89.34" not in response.text


def test_r2_1_python_mode_is_not_validated_so_the_writer_can_start_from_it() -> None:
    constructed = Money.model_construct(amount=True, currency="EUR")
    assert constructed.model_dump()["amount"] is True


# ------------------------------------------------- R2-2: a list-held or dict-held instant is .mmmZ
class _Pings(WireModel):
    """Test-local plant: no spec field holds a list of instants today (InvoiceView-shaped)."""

    at: list[AwareDatetime]
    nested: list[list[AwareDatetime]]


def test_r2_2_a_list_held_instant_is_written_mmmz_and_equals_to_wire_json() -> None:
    pings = _Pings(at=[SUB_MS, SUB_MS], nested=[[SUB_MS]])
    instant = "2026-08-30T16:20:20.442Z"
    expected = f'{{"at":["{instant}","{instant}"],"nested":[["{instant}"]]}}'
    assert pings.model_dump_json() == expected
    assert to_wire_json(pings) == expected
    assert pings.model_dump(mode="json")["at"] == ["2026-08-30T16:20:20.442Z"] * 2


def test_r2_2_a_dict_held_instant_in_an_envelope_payload_equals_to_wire_json() -> None:
    envelope = Envelope(
        event_id=UUID(int=1),
        event_type="order.placed.v1",
        aggregate_id=UUID(int=2),
        correlation_id=UUID(int=3),
        causation_id=UUID(int=4),
        occurred_at=SUB_MS,
        payload={"orderDate": SUB_MS, "dates": [SUB_MS], "nested": {"at": SUB_MS}, "n": 1},
    )
    written = envelope.model_dump_json()
    assert written == to_wire_json(envelope)
    assert not re.search(r"\.\d{3}\d+Z", written), written  # no microsecond instant anywhere
    payload = json.loads(written)["payload"]
    assert payload == {
        "orderDate": "2026-08-30T16:20:20.442Z",
        "dates": ["2026-08-30T16:20:20.442Z"],
        "nested": {"at": "2026-08-30T16:20:20.442Z"},
        "n": 1,
    }


@pytest.mark.parametrize("held", ["direct", "in a list", "in a nested dict"])
def test_r2_1_to_wire_json_refuses_an_unvalidated_model_held_in_an_envelope_payload(
    held: str,
) -> None:
    bad = Money.model_construct(amount=89.34, currency="EUR")
    payloads: dict[str, dict[str, Any]] = {
        "direct": {"money": bad},
        "in a list": {"money": [bad]},
        "in a nested dict": {"a": {"money": bad}},
    }
    payload = payloads[held]
    envelope = Envelope(
        event_id=UUID(int=1),
        event_type="order.placed.v1",
        aggregate_id=UUID(int=2),
        correlation_id=UUID(int=3),
        causation_id=UUID(int=4),
        occurred_at=SUB_MS,
        payload=payload,
    )
    with pytest.raises(PydanticSerializationError, match="amount"):
        envelope.model_dump_json()
    with pytest.raises(PydanticSerializationError, match="amount"):
        to_wire_json(envelope)


def test_r2_2_a_datetime_less_dict_payload_is_untouched() -> None:
    assert (
        Envelope(
            event_id=UUID(int=1),
            event_type="order.placed.v1",
            aggregate_id=UUID(int=2),
            correlation_id=UUID(int=3),
            causation_id=UUID(int=4),
            occurred_at=SUB_MS,
            payload={"a": [1, "x"], "b": {"c": None}},
        )
        .model_dump_json()
        .endswith('"payload":{"a":[1,"x"],"b":{"c":null}}}')
    )


# ------------------------------------------------- R2-3 / R2-4: the docstring tells the truth
def test_r2_3_the_module_docstring_no_longer_claims_what_the_code_does_not_do() -> None:
    import otc_contracts.wire as wire

    doc = wire.__doc__ or ""
    assert "deliberately not the writer" not in doc
    assert "when parsing" not in doc.split("Integers are strict")[1].splitlines()[0]
    assert "NOT wire models" in doc


def test_r2_4_the_generated_root_models_are_not_wire_models() -> None:
    from pydantic import RootModel

    from otc_contracts.generated import asyncapi

    for name in ("Quantity", "ProductCode"):
        cls = getattr(asyncapi, name)
        assert issubclass(cls, RootModel)
        assert not issubclass(cls, WireModel)
