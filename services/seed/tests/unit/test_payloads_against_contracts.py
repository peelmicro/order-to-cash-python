"""The outbox payloads: validated against the generated contract, written by the one serializer.

R-map (feature_list.json id 12, acceptance 2/3; CLAUDE.md "one serializer configuration"): all 50
seeded payloads (the population is `default_dataset()`'s outbox rows, and its event types are a
literal set below) parse into their contract payload model, are written by `to_wire_json`
(compact, non-ASCII raw, camelCase, `.mmmZ`), and are semantically equal to the payload #7 wrote
(key order is never a parity claim).
"""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from otc_contracts import FACT_MODELS, WireModel, from_wire_json, to_wire_json
from otc_seed.application import default_dataset
from otc_seed.infrastructure.payloads import payload_json, payload_model

SEEDED_EVENT_TYPES = {
    "order.placed.v1",
    "order.confirmed.v1",
    "order.completed.v1",
    "order.cancelled.v1",
    "order.despatched.v1",
    "stock.reserved.v1",
    "stock.released.v1",
    "credit.approved.v1",
    "credit.released.v1",
    "credit.rejected.v1",
    "invoice.issued.v1",
    "payment.received.v1",
}


def _facts() -> list[Any]:
    return [
        f
        for s in default_dataset().sagas
        for f in (*s.orders_outbox, *s.fulfillment_outbox, *s.billing_outbox)
    ]


def test_the_population_is_fifty_facts_of_twelve_registered_types() -> None:
    facts = _facts()
    assert len(facts) == 50
    assert {f.event_type for f in facts} == SEEDED_EVENT_TYPES
    assert set(FACT_MODELS) >= SEEDED_EVENT_TYPES


def test_every_payload_is_the_contract_models_own_wire_form() -> None:
    for fact in _facts():
        text = payload_json(fact.event_type, fact.payload)
        model = from_wire_json(payload_model(fact.event_type), text)
        assert to_wire_json(model) == text  # a fixed point of the one serializer
        assert json.dumps(json.loads(text), separators=(",", ":"), ensure_ascii=False) == text


def test_every_payload_is_semantically_equal_to_the_one_7_wrote(
    number7_dataset: dict[str, Any],
) -> None:
    theirs = [
        row["payload"]
        for saga in number7_dataset["sagas"]
        for row in (*saga["ordersOutbox"], *saga["fulfillmentOutbox"], *saga["billingOutbox"])
    ]
    ours = [json.loads(payload_json(f.event_type, f.payload)) for f in _facts()]
    assert ours == theirs
    assert len(ours) == 50


def test_the_text_has_no_insignificant_whitespace_and_writes_non_ascii_raw() -> None:
    cancelled = next(
        f for f in _facts() if f.event_type == "order.placed.v1" and "notes" in f.payload
    )
    text = payload_json(cancelled.event_type, cancelled.payload)
    assert "—" in text  # the em dash of the notes, raw
    assert "\\u2014" not in text
    for fact in _facts():
        rendered = payload_json(fact.event_type, fact.payload)
        assert "\n" not in rendered
        assert '", "' not in rendered
        assert '": ' not in rendered


def test_an_instant_is_written_with_milliseconds_and_z() -> None:
    placed = next(f for f in _facts() if f.event_type == "order.placed.v1")
    assert '"orderDate":"2026-06-01T09:00:00.000Z"' in payload_json(
        placed.event_type, placed.payload
    )


def test_a_payload_the_contract_would_refuse_fails_the_seed() -> None:
    placed = next(f for f in _facts() if f.event_type == "order.placed.v1")
    with pytest.raises(ValidationError):
        payload_json(placed.event_type, {**placed.payload, "orderReference": "ORD-1"})
    with pytest.raises(ValidationError):
        payload_json(placed.event_type, {**placed.payload, "totalAmount": 161.3})
    with pytest.raises(ValidationError):
        payload_json(placed.event_type, {**placed.payload, "totalAmount": "16130"})
    missing = {k: v for k, v in placed.payload.items() if k != "buyerGln"}
    with pytest.raises(ValidationError):
        payload_json(placed.event_type, missing)


def test_the_payload_model_of_a_type_is_the_envelopes_payload_annotation() -> None:
    for event_type in SEEDED_EVENT_TYPES:
        model: type[WireModel] = payload_model(event_type)
        assert model is FACT_MODELS[event_type].model_fields["payload"].annotation
    with pytest.raises(KeyError):
        payload_model("order.unknown.v1")
