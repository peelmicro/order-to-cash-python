"""J1 (R50, R51, PR14, PR46): the timeline as stored, against a real MongoDB.

Fixtures never satisfy the relation by accident: the arrival order differs from the `occurredAt`
order, and the `eventId`s are SCRAMBLED against `occurredAt`: their order is neither ascending nor
descending with time (placed 3, reserved 5, approved 1, confirmed 4, despatched 2), so neither
`eventId` ascending nor `eventId` descending reproduces the expected order, and the arrival order
is a third order. The causal chain follows the
`occurredAt` order, which is the live shape; the chain only orders entries that SHARE an instant,
so it cannot rescue an implementation that ignores `occurredAt`. Every id of an envelope is
distinct.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_projector.application.outcome import ProjectionOutcome

pytestmark = pytest.mark.integration

ORDER = uuid.UUID("0a0b0c0d-8888-4000-8000-0000000000b1")


def at(second: int, millisecond: int = 0) -> datetime:
    return datetime(2026, 5, 1, 9, 0, second, millisecond * 1000, tzinfo=UTC)


def eid(number: int) -> uuid.UUID:
    return uuid.UUID(f"{number:08x}-0000-4000-8000-{number * 977:012x}")


def chain(facts: Any) -> list[Any]:
    """Five facts of one order, in occurredAt order: placed t=1, reserved t=2, approved t=3,
    confirmed t=4, despatched t=5. Each cites its predecessor (the live causal chain). The
    eventIds are scrambled against time (see the module docstring): sorting by eventId, ascending or
    descending, does not give the occurredAt order."""
    spec = [
        ("order.placed.v1", 1, 0xA0003, 0xC0000),
        ("stock.reserved.v1", 2, 0xA0005, 0xA0003),
        ("credit.approved.v1", 3, 0xA0001, 0xA0005),
        ("order.confirmed.v1", 4, 0xA0004, 0xA0001),
        ("order.despatched.v1", 5, 0xA0002, 0xA0004),
    ]
    return [
        facts.build(
            event_type,
            correlation_id=ORDER,
            event_id=eid(event),
            causation_id=eid(cause),
            occurred_at=at(second, 100 + second),
        )
        for event_type, second, event, cause in spec
    ]


async def test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival(  # noqa: E501
    read_model: Any, facts: Any
) -> None:
    placed, reserved, approved, confirmed, despatched = chain(facts)
    # arrival: despatched, approved, reserved, placed, confirmed. The occurredAt order is placed,
    # reserved, approved, confirmed, despatched; the eventId order is approved, despatched, placed,
    # confirmed, reserved (and its reverse): three distinct orders, none the reverse of another
    arrival = [despatched, approved, reserved, placed, confirmed]
    for event in arrival:
        await read_model.apply(event)
    document = await read_model.document(ORDER)
    entries = document["events"]
    assert [e["eventId"] for e in entries] == [
        str(e.event_id) for e in (placed, reserved, approved, confirmed, despatched)
    ], "the timeline is not ordered by occurredAt"
    expected_summaries = [
        "Order ORD-000101 placed for ACME",
        "Stock reserved for 2 line(s)",
        "Credit hold of 92.45 EUR approved",
        "Order confirmed (ORDRSP)",
        "Despatch DES-000203 created",
    ]
    expected_instants = [
        "2026-05-01T09:00:01.101Z",
        "2026-05-01T09:00:02.102Z",
        "2026-05-01T09:00:03.103Z",
        "2026-05-01T09:00:04.104Z",
        "2026-05-01T09:00:05.105Z",
    ]
    for entry, event, summary, instant in zip(
        entries,
        (placed, reserved, approved, confirmed, despatched),
        expected_summaries,
        expected_instants,
        strict=True,
    ):
        assert entry["eventId"] == str(event.event_id)
        assert entry["eventType"] == event.event_type
        assert entry["occurredAt"] == instant
        assert entry["summary"] == summary
        assert entry["causationId"] == str(event.causation_id)
    assert document["status"] == "despatched"


async def test_r51_leaves_the_read_model_document_unchanged_when_a_fact_with_an_already_present_event_id_is_redelivered(  # noqa: E501
    read_model: Any, facts: Any
) -> None:
    placed, reserved, *_ = chain(facts)
    await read_model.apply(placed)
    first = await read_model.apply(reserved)
    before = await read_model.raw(ORDER)
    redelivery = await read_model.apply(reserved)
    after = await read_model.raw(ORDER)
    assert first.outcome is ProjectionOutcome.PROCESSED
    assert redelivery.outcome is ProjectionOutcome.DUPLICATE, "the writer did not report DUPLICATE"
    assert redelivery.documents == [], "the post-apply callback ran for a redelivery"
    assert after == before, "the stored bytes changed on a redelivery"
    document = await read_model.document(ORDER)
    assert len(document["events"]) == 2


async def test_pr14_updated_at_is_the_greatest_occurred_at_not_the_latest_arrival(
    read_model: Any, facts: Any
) -> None:
    placed, reserved, approved, *_ = chain(facts)
    await read_model.apply(approved)  # t=3 arrives first
    assert (await read_model.document(ORDER))["updatedAt"] == "2026-05-01T09:00:03.103Z"
    await read_model.apply(placed)  # an OLDER fact arrives last
    await read_model.apply(reserved)
    document = await read_model.document(ORDER)
    assert document["updatedAt"] == "2026-05-01T09:00:03.103Z", (
        "updatedAt followed the latest arrival instead of the greatest occurredAt"
    )


async def test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim(
    read_model: Any, facts: Any
) -> None:
    note = "Cliente pidió anulación — $status"
    event = facts.build(
        "order.cancelled.v1",
        correlation_id=ORDER,
        payload={
            "cancellation_reason": "operator_cancelled",
            "note": note,
            "compensation_steps": [],
        },
    )
    await read_model.apply(event)
    document = await read_model.document(ORDER)
    (entry,) = document["events"]
    assert entry["detail"]["note"] == note
    assert entry["detail"]["cancellationReason"] == "operator_cancelled"
    assert document["cancellationReason"] == "operator_cancelled"
    assert document["status"] == "cancelled"
