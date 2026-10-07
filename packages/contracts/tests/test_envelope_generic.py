"""OI20 (backlog 203 item 2) and OI19's one truncation: the generic `Envelope[P]`, `wire_instant`.

The payload is a test-local `WireModel` holding a `datetime`, a `list[datetime]` and an `int`, with
instants that carry microseconds (`.123987`): the case that makes pydantic's own JSON mode write
`.123987Z` and `timestamptz(3)` round to `.124`.
"""

import re
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import AwareDatetime, ValidationError
from pydantic_core import PydanticSerializationError

from otc_contracts import Envelope, WireModel, format_instant, to_wire_json, wire_instant
from otc_contracts.generated import asyncapi

EVENT_ID = UUID("11111111-1111-4111-8111-111111111111")
AGGREGATE_ID = UUID("22222222-2222-4222-8222-222222222222")
CORRELATION_ID = UUID("33333333-3333-4333-8333-333333333333")
CAUSATION_ID = UUID("44444444-4444-4444-8444-444444444444")


class Local(WireModel):
    taken_at: AwareDatetime
    history: list[AwareDatetime]
    amount: int


def local_payload() -> Local:
    return Local(
        taken_at=datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=UTC),
        history=[
            datetime(2026, 10, 6, 9, 30, 6, 999999, tzinfo=UTC),
            datetime(2026, 10, 6, 9, 30, 7, 1, tzinfo=UTC),
        ],
        amount=8934,
    )


def envelope_of(payload: Local) -> Envelope[Local]:
    # built the way the writer builds it: from the typed payload's python-mode dump
    return Envelope[Local].model_validate(
        {
            "event_id": EVENT_ID,
            "event_type": "order.placed.v1",
            "aggregate_id": AGGREGATE_ID,
            "correlation_id": CORRELATION_ID,
            "causation_id": CAUSATION_ID,
            "occurred_at": datetime(2026, 10, 6, 9, 30, 4, 442987, tzinfo=UTC),
            "payload": payload.model_dump(mode="python"),
        }
    )


FRACTION = re.compile(r"\d{2}:\d{2}:\d{2}\.(\d+)")


def test_oi20_model_dump_json_equals_to_wire_json() -> None:
    envelope = envelope_of(local_payload())
    assert envelope.model_dump_json() == to_wire_json(envelope)


def test_oi20_no_path_writes_an_instant_with_more_than_three_fractional_digits() -> None:
    envelope = envelope_of(local_payload())
    for path, text in (
        ("model_dump_json", envelope.model_dump_json()),
        ("to_wire_json", to_wire_json(envelope)),
    ):
        fractions = FRACTION.findall(text)
        # occurredAt + takenAt + two list-held instants: the list-held ones are the deep case
        assert len(fractions) == 4, f"{path}: expected 4 instants, found {fractions} in {text}"
        assert all(len(f) == 3 for f in fractions), f"{path} wrote a long fraction: {text}"
    assert '"occurredAt":"2026-10-06T09:30:04.442Z"' in to_wire_json(envelope)
    assert '"history":["2026-10-06T09:30:06.999Z","2026-10-06T09:30:07.000Z"]' in to_wire_json(
        envelope
    )


def test_oi20_a_payload_copied_past_validation_is_refused_by_model_dump_json_and_by_to_wire_json() -> (  # noqa: E501
    None
):
    bad_payload = local_payload().model_copy(update={"amount": 89.34})
    assert bad_payload.amount == 89.34, "the copy must have skipped validation (the premise)"
    envelope = envelope_of(local_payload()).model_copy(update={"payload": bad_payload})
    with pytest.raises(PydanticSerializationError, match="amount"):
        envelope.model_dump_json()
    with pytest.raises(ValidationError, match="amount"):
        to_wire_json(envelope)


def test_the_generic_envelope_has_the_generated_envelopes_fields_aliases_order_and_pattern() -> (
    None
):
    generic = Envelope[dict[str, int]]
    generated = asyncapi.Envelope
    assert list(generic.model_fields) == list(generated.model_fields)
    for name, field in generated.model_fields.items():
        assert generic.model_fields[name].alias == field.alias, name
        assert generic.model_fields[name].serialization_alias == field.serialization_alias, name

    def pattern_of(model: type[WireModel]) -> str:
        metadata = model.model_fields["event_type"].metadata
        patterns = [m.pattern for m in metadata if hasattr(m, "pattern")]
        assert len(patterns) == 1
        return str(patterns[0])

    assert pattern_of(generic) == pattern_of(generated) == "^[a-z]+\\.[a-z_]+\\.v[0-9]+$"
    document = Envelope[dict[str, int]](
        event_id=uuid4(),
        event_type="a.b.v1",
        aggregate_id=uuid4(),
        correlation_id=uuid4(),
        causation_id=uuid4(),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"a": 1},
    )
    assert list(document.model_dump(mode="json")) == [
        "eventId",
        "eventType",
        "aggregateId",
        "correlationId",
        "causationId",
        "occurredAt",
        "payload",
    ]


def test_wire_instant_truncates_and_agrees_with_format_instant() -> None:
    plus_two = timezone(timedelta(hours=2))
    base = datetime(2026, 10, 6, 9, 30, 5, tzinfo=UTC)
    swept = 0
    for micro in range(0, 1_000_000, 997):
        for zone in (UTC, plus_two):
            value = base.replace(microsecond=micro).astimezone(zone)
            result = wire_instant(value)
            swept += 1
            assert result.microsecond == micro // 1000 * 1000, (micro, result)
            assert result.microsecond % 1000 == 0
            assert result.utcoffset() == timedelta(0)
            assert result == value.replace(microsecond=micro // 1000 * 1000)
            assert format_instant(result) == format_instant(value)
    assert swept > 1000, "the sweep must cover the whole microsecond range"
    assert wire_instant(datetime(2026, 1, 1, 0, 0, 0, 999999, tzinfo=UTC)).microsecond == 999000
    with pytest.raises(ValueError, match="timezone-aware"):
        wire_instant(datetime(2026, 1, 1, 0, 0, 0, 123987))
