"""R11 at the domain level: the pure envelope guard (`specs/outbox_and_idempotency/design.md` 4.6).

No store, no framework. The catalogue case reads `otc_contracts.FACT_MODELS` at run time (a test
dependency only: the kernel itself imports nothing from `contracts`).
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from otc_contracts import FACT_MODELS
from otc_shared_kernel import (
    EVENT_TYPE_PATTERN,
    DomainError,
    IncompleteDomainEventEnvelopeError,
    UniqueId,
    validate_domain_event_envelope,
)

ASYNCAPI = Path(__file__).resolve().parents[3] / "specs" / "shared" / "asyncapi.yaml"


def _nil_unique_id() -> UniqueId:
    forced = UniqueId.new()
    object.__setattr__(
        forced, "value", uuid.UUID(int=0)
    )  # bypasses the frozen check and __post_init__
    return forced


def complete() -> dict[str, Any]:
    return {
        "event_id": UniqueId.new(),
        "event_type": "order.placed.v1",
        "aggregate_id": UniqueId.new(),
        "correlation_id": UniqueId.new(),
        "causation_id": UniqueId.new(),
        "occurred_at": datetime(2026, 10, 6, 9, 30, 0, 123000, tzinfo=UTC),
    }


def test_r11_event_envelope_accepts_a_complete_envelope_and_every_event_type_of_the_catalogue() -> (
    None
):
    validate_domain_event_envelope(**complete())
    assert FACT_MODELS, "the catalogue is empty: this case would pass vacuously"
    for event_type in FACT_MODELS:
        validate_domain_event_envelope(**{**complete(), "event_type": event_type})


ID_FIELDS = ["event_id", "aggregate_id", "correlation_id", "causation_id"]
ID_CASES: list[tuple[str, Any]] = [
    ("none", None),
    ("plain_uuid", uuid.uuid4()),
    ("nil_unique_id", _nil_unique_id()),
]
INSTANT_CASES: list[tuple[str, Any]] = [
    ("none", None),
    ("naive", datetime(2026, 10, 6, 9, 30, 0)),
    ("plus_two", datetime(2026, 10, 6, 9, 30, 0, tzinfo=timezone(timedelta(hours=2)))),
]
EVENT_TYPE_CASES: list[tuple[str, Any]] = [
    ("none", None),
    ("empty", ""),
    ("capitalised", "Order.Placed.v1"),
    ("two_segments", "order.placed"),
    ("version_without_digits", "order.placed.v"),
    ("no_dot_after_aggregate", "orderplaced.v1"),
    ("trailing_space", "order.placed.v1 "),
    ("trailing_newline", "order.placed.v1\n"),
]

CASES: list[Any] = [
    pytest.param(field, value, id=f"{field}-{label}")
    for field in ID_FIELDS
    for label, value in ID_CASES
]
CASES += [
    pytest.param("occurred_at", value, id=f"occurred_at-{label}") for label, value in INSTANT_CASES
]
CASES += [
    pytest.param("event_type", value, id=f"event_type-{label}") for label, value in EVENT_TYPE_CASES
]


@pytest.mark.parametrize(("field", "bad"), CASES)
def test_r11_event_envelope_refuses_an_envelope_with_an_absent_null_or_empty_field_and_an_event_type_that_does_not_match_the_pattern(  # noqa: E501
    field: str, bad: Any
) -> None:
    with pytest.raises(IncompleteDomainEventEnvelopeError) as raised:
        validate_domain_event_envelope(**{**complete(), field: bad})
    assert isinstance(raised.value, DomainError)
    assert raised.value.code == "domain_event_envelope.incomplete"
    assert field in raised.value.message, f"the message must name {field!r}: {raised.value.message}"
    # the message names ONLY the failing field: a sibling name in it would hide a wrong check
    siblings = [f for f in [*ID_FIELDS, "occurred_at", "event_type"] if f != field]
    assert not [s for s in siblings if s in raised.value.message]


def test_the_event_type_pattern_is_the_asyncapi_envelope_pattern() -> None:
    document = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    pattern = document["components"]["schemas"]["Envelope"]["properties"]["eventType"]["pattern"]
    assert pattern == "^" + EVENT_TYPE_PATTERN + "$"
