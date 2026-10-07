"""Domain event -> wire fact, every field against a distinct source value (feature 14 task 3.9).

No store, no broker. Each event is built directly with values that are pairwise distinct across the
whole test (three amounts, four ids, three instants, two lines differing in every field), so a
mapper that reads `total_amount` for `initial_amount`, `supplier_gln` for `buyer_gln`, or
`occurred_at` for `order_date` produces a value the assertion cannot mistake for the right one.
"""

import dataclasses
import json
import re
import uuid
from datetime import UTC, datetime
from typing import TypedDict

import pytest

from otc_contracts import to_wire_json
from otc_contracts.generated import asyncapi
from otc_orders.domain.events import (
    OrderCancelled,
    OrderCompleted,
    OrderConfirmed,
    OrderPlaced,
    OrderPlacedLine,
)
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import (
    CompensationStep,
    CompensationStepKind,
)
from otc_orders.infrastructure.outbox.errors import UnmappedDomainEventError
from otc_orders.infrastructure.outbox.payloads import build_fact, narrow
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{n:012d}"))


EVENT_ID, AGGREGATE_ID, CORRELATION_ID, CAUSATION_ID = uid(1), uid(2), uid(3), uid(4)
OCCURRED_AT = datetime(2026, 10, 6, 9, 30, 5, 123000, tzinfo=UTC)
ORDER_DATE = datetime(2026, 10, 6, 8, 15, 0, 456000, tzinfo=UTC)
CONFIRMED_AT = datetime(2026, 10, 6, 9, 31, 7, 789000, tzinfo=UTC)  # differs from OCCURRED_AT


class Identity(TypedDict):
    event_id: UniqueId
    aggregate_id: UniqueId
    correlation_id: UniqueId
    causation_id: UniqueId
    occurred_at: datetime


def identity(occurred_at: datetime = OCCURRED_AT) -> Identity:
    return Identity(
        event_id=EVENT_ID,
        aggregate_id=AGGREGATE_ID,
        correlation_id=CORRELATION_ID,
        causation_id=CAUSATION_ID,
        occurred_at=occurred_at,
    )


def placed() -> OrderPlaced:
    return OrderPlaced(
        **identity(),
        order_reference=OrderNumber("ORD-000123"),
        retailer_code="RET-77",
        company_code="CMP-88",
        buyer_gln=GLN("4012345000009"),
        supplier_gln=GLN("5412345000006"),
        currency="EUR",
        order_date=ORDER_DATE,
        lines=(
            OrderPlacedLine(
                product_code="SKU-A",
                description="Alpha pallet",
                quantity=Quantity(3),
                unit_price=Money(1999, "EUR"),
                line_discount=Money(250, "EUR"),
            ),
            OrderPlacedLine(
                product_code="SKU-B",
                description=None,
                quantity=Quantity(2),
                unit_price=Money(1234, "EUR"),
                line_discount=Money(100, "EUR"),
            ),
        ),
        initial_amount=Money(8465, "EUR"),
        initial_discount=Money(350, "EUR"),
        total_amount=Money(8115, "EUR"),
        notes="dock 4",
    )


def assert_envelope(event_type: str, built_json: str) -> None:
    for expected in (
        str(EVENT_ID),
        str(AGGREGATE_ID),
        str(CORRELATION_ID),
        str(CAUSATION_ID),
    ):
        assert expected in built_json
    assert f'"eventType":"{event_type}"' in built_json
    assert '"occurredAt":"2026-10-06T09:30:05.123Z"' in built_json


def test_order_placed_maps_every_payload_field_from_its_own_source() -> None:
    built = build_fact(placed())
    payload = built.payload
    assert isinstance(payload, asyncapi.OrderPlacedPayload)
    assert payload.order_reference == "ORD-000123"
    assert payload.retailer_code == "RET-77"
    assert payload.company_code == "CMP-88"
    assert payload.buyer_gln == "4012345000009"
    assert payload.supplier_gln == "5412345000006"
    assert payload.currency == "EUR"
    assert payload.order_date == ORDER_DATE
    assert payload.initial_amount == 8465
    assert payload.initial_discount == 350
    assert payload.total_amount == 8115
    assert payload.notes == "dock 4"
    first, second = payload.lines
    assert (first.product_code, first.description, first.quantity) == ("SKU-A", "Alpha pallet", 3)
    assert (first.unit_price, first.line_discount) == (1999, 250)
    assert (second.product_code, second.description, second.quantity) == ("SKU-B", None, 2)
    assert (second.unit_price, second.line_discount) == (1234, 100)
    assert built.occurred_at == OCCURRED_AT
    assert_envelope("order.placed.v1", to_wire_json(built.envelope))


def test_order_placed_without_notes_omits_the_key_on_the_wire() -> None:
    payload_json = to_wire_json(build_fact(dataclasses.replace(placed(), notes=None)).payload)
    assert '"notes"' not in payload_json
    assert '"description"' in payload_json  # the first line's; the second line's None is omitted


def test_order_confirmed_maps_every_payload_field_from_its_own_source() -> None:
    event = OrderConfirmed(
        **identity(),
        order_reference=OrderNumber("ORD-000124"),
        retailer_code="RET-78",
        company_code="CMP-89",
        currency="GBP",
        total_amount=Money(7321, "GBP"),
        confirmed_at=CONFIRMED_AT,
    )
    built = build_fact(event)
    payload = built.payload
    assert isinstance(payload, asyncapi.OrderConfirmedPayload)
    assert payload.order_reference == "ORD-000124"
    assert (payload.retailer_code, payload.company_code, payload.currency) == (
        "RET-78",
        "CMP-89",
        "GBP",
    )
    assert payload.total_amount == 7321
    assert payload.confirmed_at == CONFIRMED_AT
    assert payload.confirmed_at != built.occurred_at
    assert_envelope("order.confirmed.v1", to_wire_json(built.envelope))


def test_order_completed_maps_every_payload_field_from_its_own_source() -> None:
    event = OrderCompleted(
        **identity(),
        order_reference=OrderNumber("ORD-000125"),
        retailer_code="RET-79",
        company_code="CMP-90",
        currency="USD",
        total_amount=Money(6543, "USD"),
        completed_at=CONFIRMED_AT,
    )
    built = build_fact(event)
    payload = built.payload
    assert isinstance(payload, asyncapi.OrderCompletedPayload)
    assert payload.order_reference == "ORD-000125"
    assert (payload.retailer_code, payload.company_code, payload.currency) == (
        "RET-79",
        "CMP-90",
        "USD",
    )
    assert payload.total_amount == 6543
    assert payload.completed_at == CONFIRMED_AT
    assert built.occurred_at == OCCURRED_AT, (
        "the row's occurred_at is the EVENT's, not the payload's"
    )
    assert_envelope("order.completed.v1", to_wire_json(built.envelope))


def cancelled(note: str | None) -> OrderCancelled:
    return OrderCancelled(
        **identity(),
        order_reference=OrderNumber("ORD-000126"),
        retailer_code="RET-80",
        company_code="CMP-91",
        cancellation_reason=CancellationReason.CREDIT_REJECTED,
        cancelled_at=CONFIRMED_AT,
        compensation_steps=(
            CompensationStep(
                step=CompensationStepKind.STOCK_RELEASED,
                event_id=uid(5),
                event_type="stock.released.v1",
                occurred_at=ORDER_DATE,
                summary="stock released - reason: credit_rejected",
            ),
            CompensationStep(
                step=CompensationStepKind.CREDIT_RELEASED,
                event_id=None,
                event_type="credit.released.v1",
                occurred_at=OCCURRED_AT,
            ),
        ),
        note=note,
    )


def test_order_cancelled_with_a_note_and_two_compensation_steps_maps_every_field() -> None:
    built = build_fact(cancelled("operator said so"))
    payload = built.payload
    assert isinstance(payload, asyncapi.OrderCancelledPayload)
    assert payload.order_reference == "ORD-000126"
    assert (payload.retailer_code, payload.company_code) == ("RET-80", "CMP-91")
    assert payload.cancellation_reason is asyncapi.CancellationReason.credit_rejected
    assert payload.cancelled_at == CONFIRMED_AT
    assert payload.note == "operator said so"
    first, second = payload.compensation_steps
    assert first.step is asyncapi.Step.stock_released
    assert first.event_id == uid(5).value
    assert first.event_type == "stock.released.v1"
    assert first.occurred_at == ORDER_DATE
    assert first.summary == "stock released - reason: credit_rejected"
    assert second.step is asyncapi.Step.credit_released
    assert second.event_id is None
    assert second.event_type == "credit.released.v1"
    assert second.occurred_at == OCCURRED_AT
    assert second.summary is None
    assert built.occurred_at == OCCURRED_AT, (
        "the row's occurred_at is the EVENT's, not the payload's"
    )
    assert_envelope("order.cancelled.v1", to_wire_json(built.envelope))


def test_order_cancelled_without_a_note_omits_the_note_key() -> None:
    payload_json = to_wire_json(build_fact(cancelled(None)).payload)
    assert '"note"' not in payload_json
    assert '"compensationSteps"' in payload_json


def test_a_sub_millisecond_instant_is_truncated_in_the_payload_and_the_envelope() -> None:
    event = OrderConfirmed(
        **identity(datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=UTC)),
        order_reference=OrderNumber("ORD-000124"),
        retailer_code="RET-78",
        company_code="CMP-89",
        currency="EUR",
        total_amount=Money(7321, "EUR"),
        confirmed_at=datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=UTC),
    )
    built = build_fact(event)
    assert built.occurred_at.microsecond == 123000
    assert isinstance(built.payload, asyncapi.OrderConfirmedPayload)
    assert built.payload.confirmed_at.microsecond == 123000


SUB_MS = datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=UTC)


def test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond() -> None:
    """OI19 at the mapper: each instant the four payloads carry (and the envelope's `occurredAt`,
    and a compensation step's) leaves as `.123`, never `.123987` and never rounded to `.124`."""
    identity_sub_ms = identity(SUB_MS)
    placed_event = dataclasses.replace(placed(), occurred_at=SUB_MS, order_date=SUB_MS)
    confirmed_event = OrderConfirmed(
        **identity_sub_ms,
        order_reference=OrderNumber("ORD-000124"),
        retailer_code="RET-78",
        company_code="CMP-89",
        currency="EUR",
        total_amount=Money(7321, "EUR"),
        confirmed_at=SUB_MS,
    )
    completed_event = OrderCompleted(
        **identity_sub_ms,
        order_reference=OrderNumber("ORD-000125"),
        retailer_code="RET-79",
        company_code="CMP-90",
        currency="USD",
        total_amount=Money(6543, "USD"),
        completed_at=SUB_MS,
    )
    cancelled_event = dataclasses.replace(
        cancelled("n"),
        occurred_at=SUB_MS,
        cancelled_at=SUB_MS,
        compensation_steps=(
            CompensationStep(
                step=CompensationStepKind.STOCK_RELEASED,
                event_id=uid(5),
                event_type="stock.released.v1",
                occurred_at=SUB_MS,
            ),
        ),
    )
    for event in (placed_event, confirmed_event, completed_event, cancelled_event):
        wire = json.loads(to_wire_json(build_fact(event).envelope))
        instants = re.findall(r"\d{2}:\d{2}:\d{2}\.(\d+)Z", json.dumps(wire))
        assert instants, f"{type(event).__name__}: no instant found"
        assert set(instants) == {"123"}, f"{type(event).__name__}: instants {instants}"
        built = build_fact(event)
        assert built.occurred_at.microsecond == 123000
        for value in vars(built.payload).values():
            if isinstance(value, datetime):
                assert value.microsecond == 123000
    cancelled_payload_ = build_fact(cancelled_event).payload
    assert isinstance(cancelled_payload_, asyncapi.OrderCancelledPayload)
    assert [s.occurred_at.microsecond for s in cancelled_payload_.compensation_steps] == [123000]


def test_an_unknown_event_class_is_refused_by_name() -> None:
    class OrderShipped:
        pass

    with pytest.raises(UnmappedDomainEventError, match="OrderShipped") as raised:
        narrow(OrderShipped())
    assert raised.value.event_class == "OrderShipped"
